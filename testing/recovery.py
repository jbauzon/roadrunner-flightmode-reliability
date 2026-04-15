"""
testing.recovery -- Auto-recovery manager for unattended batch testing.

Classifies failures and determines the appropriate recovery action.
All recovery actions that don't require physical intervention are
executed automatically. Actions that require physical intervention
are logged and the UUT is skipped.

Failure classification:
  SOFT  — transient, recoverable without hardware change
          (connection hiccup, IBIT cooldown, stuck mode)
  HARD  — firmware/hardware state requiring vehicle reboot
          (TERMINAL mode, unrecoverable ARM failure)
  FATAL — actual test failure (mistracking detected)
          (these count toward the 3x permanent skip threshold)

Recovery actions:
  RECONNECT       — re-establish MAVLink connection with backoff
  WAIT_COOLDOWN   — wait for IBIT cooldown to expire
  MODE_RESET      — send OFF mode request and restart sequence
  EXTEND_CLEARING — run monitor clearing loop for longer
  SKIP            — permanently skip (TERMINAL, unrecoverable hardware)
  RETRY           — normal retry (counts toward 3x limit)
"""
from __future__ import annotations

import time
import threading
from enum import Enum
from typing import Any, Callable, Optional


class FailureClass(str, Enum):
    SOFT  = 'soft'   # transient, auto-recoverable
    HARD  = 'hard'   # requires power cycle (skip)
    FATAL = 'fatal'  # actual test failure (counts toward 3x)


class RecoveryAction(str, Enum):
    RECONNECT       = 'reconnect'
    WAIT_COOLDOWN   = 'wait_cooldown'
    MODE_RESET      = 'mode_reset'
    EXTEND_CLEARING = 'extend_clearing'
    SKIP            = 'skip'
    RETRY           = 'retry'


class RecoveryDecision:
    """Result of classifying a failure and deciding recovery action."""

    def __init__(self, failure_class: FailureClass, action: RecoveryAction,
                 reason: str, wait_seconds: float = 0.0):
        self.failure_class = failure_class
        self.action        = action
        self.reason        = reason
        self.wait_seconds  = wait_seconds
        self.counts_toward_permanent = (failure_class == FailureClass.FATAL)

    def __repr__(self) -> str:
        return (
            f"RecoveryDecision(class={self.failure_class.value}, "
            f"action={self.action.value}, reason={self.reason!r})"
        )


class RecoveryManager:
    """
    Classifies test failures and executes auto-recovery actions.

    Usage:
        rm = RecoveryManager(on_log=win.log, on_alert=win.show_alert)
        decision = rm.classify(error_message, uut, attempt_number)
        rm.execute(decision, master, master_lock)
    """

    # IBIT cooldown period (seconds) — firmware enforces this between tests
    IBIT_COOLDOWN_S = 30.0

    # Reconnect backoff schedule (seconds between attempts)
    RECONNECT_DELAYS = [5, 10, 30, 60, 120]

    def __init__(self, on_log: Callable[[str], None],
                 on_alert: Callable[[str], None],
                 error_log: Optional[Any] = None):
        self._on_log    = on_log
        self._on_alert  = on_alert
        self._error_log = error_log

    def classify(self, error_message: str, uut: Any,
                 attempt: int = 1) -> RecoveryDecision:
        """
        Classify a failure and decide the recovery action.

        Args:
            error_message: The exception message from the failed test
            uut: The UUT object (for serial number and history)
            attempt: Which attempt number this is (1-based)

        Returns:
            RecoveryDecision with action and metadata
        """
        msg = error_message.lower()
        serial = getattr(uut, 'serial_number', 'unknown')

        # ── HARD failures — skip UUT (don't count toward 3x) ─────────────
        if 'terminal mode' in msg:
            return RecoveryDecision(
                FailureClass.HARD,
                RecoveryAction.SKIP,
                'Vehicle in TERMINAL mode — requires physical power cycle by operator',
            )

        if any(x in msg for x in ('thermal shutdown', 'thermal protection', 'overtemperature',
                                   'servo temperature', 'thermal limit')):
            return RecoveryDecision(
                FailureClass.HARD,
                RecoveryAction.SKIP,
                'Thermal shutdown detected — servo temperature limit exceeded. '
                'Allow vehicle to cool before retesting.',
            )

        # ── FATAL failures — actual mistracking (count toward 3x) ─────────
        if 'mistracking' in msg or 'ibit fail' in msg:
            return RecoveryDecision(
                FailureClass.FATAL,
                RecoveryAction.RETRY,
                f'IBIT mistracking detected — counting as failure ({attempt}/3)',
            )

        # ── SOFT failures — auto-recoverable ──────────────────────────────

        # Connection issues — auto-reconnect
        if any(x in msg for x in ('heartbeat', 'connection', 'no heartbeat',
                                   'lost connection', 'socket', 'network')):
            delay = self.RECONNECT_DELAYS[min(attempt - 1, len(self.RECONNECT_DELAYS) - 1)]
            return RecoveryDecision(
                FailureClass.SOFT,
                RecoveryAction.RECONNECT,
                f'Connection failure — auto-reconnecting in {delay}s',
                wait_seconds=delay,
            )

        # IBIT cooldown — auto-wait
        if 'cooldown' in msg or 'too soon' in msg:
            return RecoveryDecision(
                FailureClass.SOFT,
                RecoveryAction.WAIT_COOLDOWN,
                f'IBIT cooldown active — waiting {self.IBIT_COOLDOWN_S}s',
                wait_seconds=self.IBIT_COOLDOWN_S,
            )

        # Stuck in unexpected mode — send reset
        if any(x in msg for x in ('unexpected mode', 'stuck', 'failed to enter operate',
                                   'failed to enter playback', 'failed to enter ibit',
                                   'pos_check failed', 'mode request', 'to off mode',
                                   'transitioned to off', 'vehicle transitioned to off')):
            return RecoveryDecision(
                FailureClass.SOFT,
                RecoveryAction.MODE_RESET,
                'Vehicle in unexpected mode — sending OFF command and retrying',
                wait_seconds=5.0,
            )

        # ARM failure (monitors) — try extended clearing
        if any(x in msg for x in ('arm failed', 'failed to arm', 'monitors cannot be cleared',
                                   'arm exhausted', 'monitors still set')):
            if attempt <= 2:
                return RecoveryDecision(
                    FailureClass.SOFT,
                    RecoveryAction.EXTEND_CLEARING,
                    f'ARM failed due to monitors — extending clearing duration (attempt {attempt})',
                    wait_seconds=3.0,
                )
            else:
                # After 2 extended-clearing attempts, treat as hard failure
                return RecoveryDecision(
                    FailureClass.HARD,
                    RecoveryAction.SKIP,
                    f'ARM failed after {attempt} extended-clearing attempts — hardware fault suspected',
                )

        # Timeout failures (IBIT timeout, phase timeout) — soft retry
        if any(x in msg for x in ('timeout', 'timed out', 'phase timeout')):
            return RecoveryDecision(
                FailureClass.SOFT,
                RecoveryAction.RETRY,
                f'Timeout during test — soft retry (attempt {attempt})',
                wait_seconds=10.0,
            )

        # Unknown / uncategorized — treat as soft, retry with backoff
        return RecoveryDecision(
            FailureClass.SOFT,
            RecoveryAction.RETRY,
            f'Unknown failure: {error_message[:80]} — soft retry',
            wait_seconds=5.0,
        )

    def execute(self, decision: RecoveryDecision,
                master: Optional[Any] = None,
                master_lock: Optional[Any] = None) -> bool:
        """
        Execute the recovery action.

        Args:
            decision: The RecoveryDecision from classify()
            master: MAVLink connection (for mode reset)
            master_lock: Threading lock for MAVLink access

        Returns:
            True if recovery executed, False if SKIP (UUT should be skipped)
        """
        action = decision.action

        if action == RecoveryAction.SKIP:
            self._on_log(f"  ✗ Auto-recovery: SKIP — {decision.reason}")
            self._on_alert(
                f"AUTO-RECOVERY: UUT skipped — {decision.reason}\n"
                f"Manual intervention required to resume this UUT."
            )
            if self._error_log:
                self._error_log.error(
                    'SYSTEM', 'unknown', 0,
                    f'Auto-recovery: UUT permanently skipped — {decision.reason}',
                )
            return False

        if action == RecoveryAction.RECONNECT:
            self._on_log(
                f"  → Auto-recovery: RECONNECT — waiting {decision.wait_seconds:.0f}s "
                f"before reconnect attempt"
            )
            if decision.wait_seconds > 0:
                time.sleep(decision.wait_seconds)
            return True

        if action == RecoveryAction.WAIT_COOLDOWN:
            self._on_log(
                f"  → Auto-recovery: COOLDOWN WAIT — waiting {decision.wait_seconds:.0f}s"
            )
            time.sleep(decision.wait_seconds)
            return True

        if action == RecoveryAction.MODE_RESET:
            self._on_log(
                f"  → Auto-recovery: MODE RESET — sending OFF command"
            )
            if master and master_lock:
                try:
                    from vehicle.constants import ActuationMode
                    with master_lock:
                        master.mav.pandion_rr_actuation_request_mode_send(
                            requested_mode=int(ActuationMode.OFF)
                        )
                    self._on_log("  → OFF command sent — waiting 5s for state reset")
                except Exception as e:
                    self._on_log(f"  ⚠ Mode reset command failed: {e}")
            if decision.wait_seconds > 0:
                time.sleep(decision.wait_seconds)
            return True

        if action == RecoveryAction.EXTEND_CLEARING:
            self._on_log(
                f"  → Auto-recovery: EXTENDED CLEARING — will run monitor clearing "
                f"for longer on next attempt"
            )
            if decision.wait_seconds > 0:
                time.sleep(decision.wait_seconds)
            return True

        if action == RecoveryAction.RETRY:
            self._on_log(
                f"  → Auto-recovery: RETRY — waiting {decision.wait_seconds:.0f}s"
            )
            if decision.wait_seconds > 0:
                time.sleep(decision.wait_seconds)
            return True

        return True
