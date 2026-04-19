"""Filterable log widget with level buttons and search."""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QTextEdit,
)
from datetime import datetime

from .. import theme as T


MAX_LOG_ENTRIES = 10000  # Keep last 10k entries (~300 iterations at 30 lines/iteration)


class LogWidget(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("Test Log", parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 16, 12, 10)
        layout.setSpacing(6)

        # Filter bar
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(4)

        self._filter_buttons = {}
        self._active_filters = {'ALL'}
        self._all_entries = []  # Store all (html, level, raw_text) tuples

        for level_name, color in [
            ('ALL', T.TEXT_PRIMARY), ('INFO', T.GREEN), ('WARN', T.AMBER),
            ('ERROR', T.RED), ('PASS', T.GREEN), ('FAIL', T.RED),
        ]:
            btn = QPushButton(level_name)
            btn.setCheckable(True)
            btn.setChecked(level_name == 'ALL')
            btn.setFixedHeight(24)
            btn.setStyleSheet(
                f"QPushButton {{ background: {T.BG_ELEVATED}; color: {T.TEXT_SECONDARY}; "
                f"border: 1px solid {T.BORDER}; border-radius: 3px; "
                f"padding: 2px 8px; font-size: {T.FONT_SIZE_SM}; }}"
                f"QPushButton:checked {{ background: {color}; color: {T.BG_BASE}; "
                f"border-color: {color}; font-weight: bold; }}"
            )
            btn.clicked.connect(lambda checked, name=level_name: self._toggle_filter(name))
            filter_bar.addWidget(btn)
            self._filter_buttons[level_name] = btn

        filter_bar.addStretch()

        # Search box
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search log...")
        self._search.setFixedHeight(24)
        self._search.setStyleSheet(
            f"QLineEdit {{ background: {T.BG_BASE}; color: {T.TEXT_PRIMARY}; "
            f"border: 1px solid {T.BORDER}; border-radius: 3px; "
            f"padding: 2px 8px; font-size: {T.FONT_SIZE_SM}; "
            f"font-family: {T.FONT_MONO}; }}"
        )
        self._search.textChanged.connect(self._apply_filters)
        filter_bar.addWidget(self._search)

        layout.addLayout(filter_bar)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(220)
        self.log_text.setMaximumHeight(420)
        self.log_text.document().setMaximumBlockCount(5000)
        layout.addWidget(self.log_text)

        bar = QHBoxLayout()
        bar.addStretch()
        clear_btn = QPushButton("Clear")
        clear_btn.setStyleSheet(
            f"QPushButton {{ background: {T.BG_ELEVATED}; color: {T.TEXT_SECONDARY}; "
            f"border: 1px solid {T.BORDER}; border-radius: 4px; "
            f"padding: 3px 10px; font-size: {T.FONT_SIZE_SM}; }}"
            f"QPushButton:hover {{ color: {T.TEXT_PRIMARY}; }}"
        )
        clear_btn.clicked.connect(self._clear_log)
        bar.addWidget(clear_btn)
        layout.addLayout(bar)

    def _classify_level(self, message):
        """Classify a log message into a filter level."""
        upper = message.upper()
        if 'PASS' in upper and ('IBIT PASS' in upper or '\u2713' in message):
            return 'PASS'
        if 'FAIL' in upper or '\u2717' in message:
            return 'FAIL'
        if 'ERROR' in upper:
            return 'ERROR'
        if '\u26a0' in message or 'WARNING' in upper:
            return 'WARN'
        return 'INFO'

    def _toggle_filter(self, name):
        if name == 'ALL':
            # If ALL is toggled on, deselect others
            if self._filter_buttons['ALL'].isChecked():
                self._active_filters = {'ALL'}
                for n, btn in self._filter_buttons.items():
                    btn.setChecked(n == 'ALL')
            else:
                self._filter_buttons['ALL'].setChecked(True)  # Can't deselect ALL alone
        else:
            # Deselect ALL, toggle this filter
            self._filter_buttons['ALL'].setChecked(False)
            self._active_filters.discard('ALL')
            if name in self._active_filters:
                self._active_filters.discard(name)
            else:
                self._active_filters.add(name)

            # If nothing selected, re-select ALL
            if not self._active_filters:
                self._active_filters = {'ALL'}
                self._filter_buttons['ALL'].setChecked(True)

        self._apply_filters()

    def _apply_filters(self):
        """Re-render the log with current filters."""
        search_text = self._search.text().lower()
        self.log_text.clear()
        for html, level, raw_text in self._all_entries:
            # Level filter
            if 'ALL' not in self._active_filters and level not in self._active_filters:
                continue
            # Search filter
            if search_text and search_text not in raw_text.lower():
                continue
            self.log_text.append(html)
        sb = self.log_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _clear_log(self):
        self._all_entries.clear()
        self.log_text.clear()

    def append(self, message):
        """Append a timestamped, color-coded message to the log."""
        ts = datetime.now().strftime('%H:%M:%S')
        level = self._classify_level(message)

        # Color-code by level
        color_map = {
            'PASS': T.GREEN, 'FAIL': T.RED, 'ERROR': T.RED,
            'WARN': T.AMBER, 'INFO': T.GREEN,
        }
        color = color_map.get(level, T.GREEN)
        if message.startswith('\u2550') or message.startswith('='):
            color = T.TEXT_SECONDARY

        html = (
            f'<span style="color:{T.TEXT_DISABLED};">[{ts}] </span>'
            f'<span style="color:{color};">{message}</span>'
        )

        # Store for filtering
        self._all_entries.append((html, level, message))

        # Cap list to prevent unbounded memory growth on long batch runs
        if len(self._all_entries) > MAX_LOG_ENTRIES:
            excess = len(self._all_entries) - MAX_LOG_ENTRIES
            del self._all_entries[:excess]

        # Only display if passes current filters
        search_text = self._search.text().lower() if hasattr(self, '_search') else ''
        if ('ALL' in self._active_filters or level in self._active_filters):
            if not search_text or search_text in message.lower():
                self.log_text.append(html)
                sb = self.log_text.verticalScrollBar()
                sb.setValue(sb.maximum())
