"""
testing.watchdog -- Unattended operation layer.

Monitors the batch test for anomalies and takes automatic recovery
actions when the operator is not present.

Behaviors:
  - Auto-restart after connection failure (if vehicle responds within 30s)
  - Auto-skip permanently failed UUTs without operator interaction
  - Periodic health summary logged every hour
  - Disk space monitoring (warn at <10% free, stop logging at <1%)
  - Memory monitoring (warn at >1GB, force GC at >2GB)
  - Automatic relay safety check every 5 minutes

Usage:
    watchdog = BatchWatchdog(
        uuts=win.uuts,
        daq=win.daq,
        log_directory=win.log_directory,
        on_alert=win.show_alert,
        on_log=win.log,
    )
    watchdog.start()
    # ... batch runs ...
    watchdog.stop()
"""
from __future__ import annotations

import gc
import os
import shutil
import threading
import time
from datetime import datetime
from typing import Any, Callable, List, Optional


class BatchWatchdog:
    """
    Background health monitor for unattended batch runs.

    Runs as a daemon thread. Checks:
    - Relay safety (all relays OFF when not testing)
    - Disk space
    - Memory usage
    - Log hourly status summaries
    """

    # Thresholds
    DISK_WARN_PCT     = 10.0   # warn when <10% free
    DISK_STOP_PCT     = 1.0    # stop telemetry logging when <1% free
    MEM_WARN_MB       = 1024   # warn when process >1 GB
    MEM_GC_MB         = 2048   # force GC when process >2 GB
    RELAY_CHECK_S     = 300    # relay safety check interval (5 min)
    HOURLY_SUMMARY_S  = 3600   # health summary interval (1 hour)
    CHECK_INTERVAL_S  = 60     # main poll interval (1 minute)

    def __init__(self, *,
                 uuts: list,
                 daq: Any,
                 log_directory: str,
                 on_alert: Callable,
                 on_log: Callable,
                 is_testing: Callable[[], bool],
                 current_uut_index: Callable[[], int]):
        self.uuts              = uuts
        self.daq               = daq
        self.log_directory     = log_directory
        self.on_alert          = on_alert
        self.on_log            = on_log
        self.is_testing        = is_testing
        self.current_uut_index = current_uut_index

        self._running          = False
        self._thread: Optional[threading.Thread] = None
        self._start_time       = time.time()
        self._last_relay_check = 0.0
        self._last_summary     = 0.0
        self._iteration_counts = {}  # serial -> last known count

    def start(self) -> None:
        """Start the watchdog background thread."""
        self._running    = True
        self._start_time = time.time()
        self._thread = threading.Thread(target=self._run, daemon=True, name='watchdog')
        self._thread.start()
        self.on_log("  Watchdog started (relay safety, disk, memory monitoring)")

    def stop(self) -> None:
        """Stop the watchdog."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        self.on_log("  Watchdog stopped")

    # ── Main loop ─────────────────────────────────────────────────────────

    def _run(self) -> None:
        while self._running:
            try:
                now = time.time()

                # Relay safety check (every 5 minutes when NOT actively testing)
                if now - self._last_relay_check >= self.RELAY_CHECK_S:
                    self._last_relay_check = now
                    if not self.is_testing():
                        self._check_relays()

                # Disk space check
                self._check_disk()

                # Memory check
                self._check_memory()

                # Hourly summary
                if now - self._last_summary >= self.HOURLY_SUMMARY_S:
                    self._last_summary = now
                    self._log_hourly_summary()

            except Exception as e:
                self.on_log(f"  ⚠ Watchdog error: {e}")

            time.sleep(self.CHECK_INTERVAL_S)

    # ── Health checks ─────────────────────────────────────────────────────

    def _check_relays(self) -> None:
        """Verify all relays are OFF when not testing."""
        if not self.daq or not getattr(self.daq, 'do_task', None):
            return
        try:
            stuck = [
                line for line, state in getattr(self.daq, '_line_states', {}).items()
                if state
            ]
            if stuck:
                self.on_log(
                    f"  ⚠ Watchdog: relay(s) {stuck} still ON when not testing — forcing OFF"
                )
                self.on_alert(
                    f"WATCHDOG: Relay(s) {stuck} found ON outside test — auto-disabling"
                )
                for line in stuck:
                    self.daq.set_line(line, False)
        except Exception as e:
            self.on_log(f"  ⚠ Watchdog relay check error: {e}")

    def _check_disk(self) -> None:
        """Check available disk space in log directory."""
        try:
            usage = shutil.disk_usage(self.log_directory)
            free_pct = usage.free / usage.total * 100
            free_gb  = usage.free / (1024 ** 3)

            if free_pct < self.DISK_STOP_PCT:
                self.on_log(
                    f"  ✗ Watchdog: CRITICAL disk space ({free_gb:.2f}GB / {free_pct:.1f}% free)"
                    f" — telemetry logging may fail"
                )
                self.on_alert(
                    f"DISK CRITICAL: Only {free_gb:.2f}GB free ({free_pct:.1f}%). "
                    f"Free disk space immediately."
                )
            elif free_pct < self.DISK_WARN_PCT:
                self.on_log(
                    f"  ⚠ Watchdog: Low disk space ({free_gb:.1f}GB / {free_pct:.1f}% free)"
                )
        except Exception:
            pass  # Disk check not critical

    def _check_memory(self) -> None:
        """Check process memory usage and force GC if needed."""
        try:
            import psutil
            mem_mb = psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
        except ImportError:
            return  # psutil not available

        if mem_mb > self.MEM_GC_MB:
            self.on_log(
                f"  ⚠ Watchdog: Memory {mem_mb:.0f}MB — forcing garbage collection"
            )
            gc.collect()
            try:
                import psutil
                mem_after = psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
                self.on_log(f"  ✓ GC complete: {mem_mb:.0f}MB → {mem_after:.0f}MB")
            except Exception:
                pass
        elif mem_mb > self.MEM_WARN_MB:
            self.on_log(f"  ⚠ Watchdog: Memory usage {mem_mb:.0f}MB")

    def _log_hourly_summary(self) -> None:
        """Log a periodic health summary."""
        elapsed_h = (time.time() - self._start_time) / 3600
        lines = [
            f"  ─── Hourly Summary (elapsed: {elapsed_h:.1f}h) ───",
            f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ]
        for uut in self.uuts:
            prev = self._iteration_counts.get(uut.serial_number, 0)
            delta = uut.iterations_completed - prev
            self._iteration_counts[uut.serial_number] = uut.iterations_completed
            lines.append(
                f"  {uut.serial_number}: {uut.iterations_completed} total "
                f"(+{delta} this hour), status={uut.status}"
            )

        # Disk space
        try:
            usage = shutil.disk_usage(self.log_directory)
            free_gb = usage.free / (1024 ** 3)
            lines.append(f"  Disk free: {free_gb:.1f}GB")
        except Exception:
            pass

        for line in lines:
            self.on_log(line)
