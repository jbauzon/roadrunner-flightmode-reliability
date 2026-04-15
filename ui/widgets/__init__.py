"""UI widgets — operator console components."""
from .primitives import StatusBadge, LED, _label, _sep, _section_title
from .header import HeaderBanner
from .setup import DAQSetupWidget, TestConfigWidget
from .uut_table import UUTTableWidget
from .status import StatusPanelWidget
from .ibit_display import IBITDisplayWidget
from .actuator_feedback import ActuatorFeedbackWidget
from .alerts import AlertBannerWidget
from .progress import ProgressWidget
from .controls import ControlButtonsWidget
from .log_widget import LogWidget
from .dialogs import AddUUTDialog
from .debug_console import DebugConsoleWidget

__all__ = [
    'StatusBadge', 'LED',
    'HeaderBanner',
    'DAQSetupWidget', 'TestConfigWidget',
    'UUTTableWidget',
    'StatusPanelWidget',
    'IBITDisplayWidget',
    'ActuatorFeedbackWidget',
    'AlertBannerWidget',
    'ProgressWidget',
    'ControlButtonsWidget',
    'LogWidget',
    'AddUUTDialog',
    'DebugConsoleWidget',
]
