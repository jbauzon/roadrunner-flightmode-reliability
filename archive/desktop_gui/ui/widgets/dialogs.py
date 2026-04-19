"""Modal dialog for adding/editing UUTs."""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QGridLayout, QLineEdit, QSpinBox, QDialogButtonBox,
)

from .. import theme as T
from .primitives import _label, _sep


class AddUUTDialog(QDialog):
    def __init__(self, parent=None, uut=None):
        super().__init__(parent)
        self.uut = uut
        self._init_ui()
        if uut:
            self._load_uut()

    def _init_ui(self):
        self.setWindowTitle("Configure UUT")
        self.setModal(True)
        self.setMinimumWidth(360)
        self.setStyleSheet(f"QDialog {{ background-color: {T.BG_SURFACE}; }}")

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 16)

        title = _label("Unit Under Test", bold=True, size=T.FONT_SIZE_LG)
        layout.addWidget(title)
        layout.addWidget(_sep())

        form = QGridLayout()
        form.setSpacing(10)
        form.setColumnStretch(1, 1)

        fields = [
            ("Serial Number:", "serial_input",  QLineEdit,  {}),
            ("IP Address:",    "ip_input",       QLineEdit,  {"placeholder": "192.168.1.100"}),
            ("Port:",          "port_input",     QSpinBox,   {"range": (1, 65535), "value": 9985}),
            ("Relay Line:",    "relay_input",    QSpinBox,   {"range": (0, 31),    "value": 0}),
        ]

        for i, (lbl_text, attr, widget_cls, opts) in enumerate(fields):
            form.addWidget(_label(lbl_text, T.TEXT_SECONDARY), i, 0)
            if widget_cls == QLineEdit:
                w = QLineEdit()
                if opts.get("placeholder"):
                    w.setPlaceholderText(opts["placeholder"])
            elif widget_cls == QSpinBox:
                w = QSpinBox()
                lo, hi = opts.get("range", (0, 100))
                w.setRange(lo, hi)
                w.setValue(opts.get("value", 0))
            setattr(self, attr, w)
            form.addWidget(w, i, 1)

        layout.addLayout(form)

        # Tip
        tip = _label(
            "Relay line must match the DAQ digital output channel "
            "wired to this vehicle's power supply.",
            T.TEXT_DISABLED, size=T.FONT_SIZE_SM
        )
        tip.setWordWrap(True)
        layout.addWidget(tip)

        layout.addWidget(_sep())

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _load_uut(self):
        self.serial_input.setText(self.uut.serial_number)
        self.ip_input.setText(self.uut.ip_address)
        self.port_input.setValue(self.uut.port)
        self.relay_input.setValue(self.uut.relay_line)

    def get_uut(self):
        """Return a new UUT from the dialog's field values."""
        from rr_test.vehicle.connection import UUT
        return UUT(
            serial_number=self.serial_input.text(),
            ip_address=self.ip_input.text(),
            port=self.port_input.value(),
            relay_line=self.relay_input.value()
        )
