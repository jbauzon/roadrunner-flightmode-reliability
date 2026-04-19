"""UUT table with fleet summary and CRUD toolbar."""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
)
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtGui import QColor

from .. import theme as T
from vehicle.constants import UUTStatus


class UUTTableWidget(QGroupBox):
    add_clicked    = pyqtSignal()
    edit_clicked   = pyqtSignal()
    remove_clicked = pyqtSignal()
    save_clicked   = pyqtSignal()
    load_clicked   = pyqtSignal()

    _STATUS_COLORS = {
        "Ready":       (T.BG_ELEVATED,  T.TEXT_SECONDARY),
        "Testing":     (T.BLUE_DIM,     T.BLUE),
        "Complete":    (T.GREEN_DIM,    T.GREEN),
        "Failed":      (T.RED_DIM,      T.RED),
        "Failed (3x)": (T.RED_DIM,      T.RED),
        "Retry":       (T.AMBER_DIM,    T.AMBER),
        "Stopped":     (T.BG_ELEVATED,  T.TEXT_DISABLED),
    }

    def __init__(self, parent=None):
        super().__init__("Unit Under Test", parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 16, 12, 10)
        layout.setSpacing(8)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        btn_styles = [
            ("+ Add",    self.add_clicked,    False),
            ("Edit",     self.edit_clicked,   False),
            ("Remove",   self.remove_clicked, True),
            ("Save",     self.save_clicked,   False),
            ("Load",     self.load_clicked,   False),
        ]
        for label, signal, danger in btn_styles:
            btn = QPushButton(label)
            if danger:
                btn.setStyleSheet(
                    f"QPushButton {{ background: {T.RED_DIM}; color: {T.RED}; "
                    f"border: 1px solid {T.RED_DIM}; border-radius: 5px; "
                    f"padding: 5px 12px; font-size: {T.FONT_SIZE_SM}; }}"
                    f"QPushButton:hover {{ background: {T.RED}; color: {T.WHITE}; }}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{ background: {T.BG_ELEVATED}; color: {T.TEXT_PRIMARY}; "
                    f"border: 1px solid {T.BORDER}; border-radius: 5px; "
                    f"padding: 5px 12px; font-size: {T.FONT_SIZE_SM}; }}"
                    f"QPushButton:hover {{ border-color: {T.TEXT_SECONDARY}; }}"
                )
            btn.clicked.connect(signal)
            toolbar.addWidget(btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Fleet summary
        self._fleet_summary = QLabel()
        self._fleet_summary.setAlignment(Qt.AlignCenter)
        self._fleet_summary.setStyleSheet(
            f"color: {T.TEXT_SECONDARY}; font-size: {T.FONT_SIZE_SM}; "
            f"padding: 6px 12px; background: {T.BG_ELEVATED}; "
            f"border: 1px solid {T.BORDER}; "
            f"border-radius: 4px; font-family: {T.FONT_MONO};"
        )
        layout.addWidget(self._fleet_summary)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(["#", "Serial", "IP Address", "Port", "Relay", "Iterations", "Status"])
        header = self.table.horizontalHeader()
        tooltips = {
            0: "Row number",
            1: "Vehicle serial number",
            2: "Vehicle MAVLink IP address",
            3: "Vehicle MAVLink UDP port",
            4: "NI-DAQmx digital output line controlling this vehicle's power relay",
            5: "Number of completed IBIT/Playback test iterations",
            6: "Current test status (Ready, Testing, Complete, Failed, Retry)",
        }
        for col, tip in tooltips.items():
            item = self.table.horizontalHeaderItem(col)
            if item:
                item.setToolTip(tip)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setMinimumHeight(120)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            f"QTableWidget::item:alternate {{ background-color: {T.BG_BASE}; }}"
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        layout.addWidget(self.table)

    def update_table(self, uuts):
        """Refresh the table from a list of UUT objects."""
        self.table.setRowCount(len(uuts))
        for i, uut in enumerate(uuts):
            items = [
                str(i + 1),
                uut.serial_number,
                uut.ip_address,
                str(uut.port),
                f"D{uut.relay_line}",
                str(uut.iterations_completed),
                uut.status,
            ]
            for j, val in enumerate(items):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignCenter)
                if j == 6:  # Status column
                    bg, fg = self._STATUS_COLORS.get(uut.status, (T.BG_ELEVATED, T.TEXT_SECONDARY))
                    item.setBackground(QColor(bg))
                    item.setForeground(QColor(fg))
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)
                self.table.setItem(i, j, item)
        self.table.resizeRowsToContents()

        # Fleet summary
        counts = {}
        for uut in uuts:
            counts[uut.status] = counts.get(uut.status, 0) + 1

        parts = []
        for status, color in [
            (UUTStatus.COMPLETE,          T.GREEN),
            (UUTStatus.FAILED,            T.RED),
            (UUTStatus.FAILED_PERMANENT,  T.RED),
            (UUTStatus.TESTING,           T.AMBER),
            (UUTStatus.READY,             T.BLUE),
            (UUTStatus.RETRY,             T.AMBER),
            (UUTStatus.STOPPED,           T.TEXT_DISABLED),
        ]:
            count = counts.get(status, 0)
            if count > 0:
                parts.append(f'<span style="color:{color};">{count} {status}</span>')

        self._fleet_summary.setText(' | '.join(parts) if parts else 'No UUTs')

    def get_selected_row(self):
        """Return the selected row index, or -1 if none."""
        selected = self.table.selectionModel().selectedRows()
        return selected[0].row() if selected else -1
