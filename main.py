#!/usr/bin/env python3
"""
Multi-UUT Flight Controller Test System - Entry Point
Version 4.8 - Descriptive IBIT CSV Logging
"""
import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QFont
from ui.main_window import MultiUUTTestGUI


def main():
    """Application entry point"""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    # Set default font
    font = QFont()
    font.setPointSize(9)
    app.setFont(font)
    
    # Create and show main window
    window = MultiUUTTestGUI()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()