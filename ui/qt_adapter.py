"""
ui.qt_adapter -- Bridges callback-based executor/preparation to Qt signals.

This is the ONLY file that couples the test execution layer to PyQt5.
The testing/ and vehicle/ layers use plain callbacks; this adapter
wires those callbacks to pyqtSignal emissions for thread-safe GUI updates.
"""
from __future__ import annotations
from PyQt5.QtCore import QObject, pyqtSignal
from testing.callbacks import ExecutorCallbacks, PreparationCallbacks


class QtExecutorBridge(QObject):
    """Emits Qt signals when executor callbacks fire.

    Usage:
        bridge = QtExecutorBridge()
        executor = UUTTestExecutor(..., callbacks=bridge.callbacks)
        bridge.sig_log.connect(gui.log_widget.append)
        bridge.sig_complete.connect(gui.on_test_complete)
        executor.start()
    """

    # Qt signals matching ExecutorCallbacks
    sig_progress = pyqtSignal(int)
    sig_iteration = pyqtSignal(int)
    sig_status = pyqtSignal(str)
    sig_complete = pyqtSignal(bool, str)
    sig_log = pyqtSignal(str)
    sig_time_expired = pyqtSignal()
    sig_statistics = pyqtSignal(object)
    sig_ibit_state = pyqtSignal(str)
    sig_connection_health = pyqtSignal(bool)
    sig_alert = pyqtSignal(str)
    sig_log_file_size = pyqtSignal(float)
    sig_test_duration = pyqtSignal(float)
    sig_armed_state = pyqtSignal(bool, int)
    sig_mode = pyqtSignal(int)
    sig_actuator_feedback = pyqtSignal(dict)
    sig_relay_state = pyqtSignal(bool)
    sig_mistracking_update = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._callbacks = ExecutorCallbacks()

        # Wire callbacks to signal emissions
        self._callbacks.on_progress = self.sig_progress.emit
        self._callbacks.on_iteration = self.sig_iteration.emit
        self._callbacks.on_status = self.sig_status.emit
        self._callbacks.on_complete = self.sig_complete.emit
        self._callbacks.on_log = self.sig_log.emit
        self._callbacks.on_time_expired = self.sig_time_expired.emit
        self._callbacks.on_statistics = self.sig_statistics.emit
        self._callbacks.on_ibit_state = self.sig_ibit_state.emit
        self._callbacks.on_connection_health = self.sig_connection_health.emit
        self._callbacks.on_alert = self.sig_alert.emit
        self._callbacks.on_log_file_size = self.sig_log_file_size.emit
        self._callbacks.on_test_duration = self.sig_test_duration.emit
        self._callbacks.on_armed_state = self.sig_armed_state.emit
        self._callbacks.on_mode = self.sig_mode.emit
        self._callbacks.on_actuator_feedback = self.sig_actuator_feedback.emit
        self._callbacks.on_relay_state = self.sig_relay_state.emit
        self._callbacks.on_mistracking_update = self.sig_mistracking_update.emit

    @property
    def callbacks(self) -> ExecutorCallbacks:
        return self._callbacks


class QtPreparationBridge(QObject):
    """Emits Qt signals when preparation callbacks fire."""

    sig_log = pyqtSignal(str)
    sig_progress = pyqtSignal(str)
    sig_armed_state = pyqtSignal(bool, int)
    sig_mode = pyqtSignal(int)
    sig_connection_health = pyqtSignal(bool)
    sig_actuator_feedback = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._callbacks = PreparationCallbacks()

        self._callbacks.on_log = self.sig_log.emit
        self._callbacks.on_progress = self.sig_progress.emit
        self._callbacks.on_armed_state = self.sig_armed_state.emit
        self._callbacks.on_mode = self.sig_mode.emit
        self._callbacks.on_connection_health = self.sig_connection_health.emit
        self._callbacks.on_actuator_feedback = self.sig_actuator_feedback.emit

    @property
    def callbacks(self) -> PreparationCallbacks:
        return self._callbacks
