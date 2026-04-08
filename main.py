#!/usr/bin/env python3
"""
Roadrunner Flight Test — Entry Point
"""
import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QFont
from ui.main_window import MultiUUTTestGUI
from ui import theme as T
from version import __version__


def main():
    app = QApplication(sys.argv)

    # Apply dark theme
    T.apply(app)

    # Base font
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    window = MultiUUTTestGUI()
    window.show()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
