@echo off
title Roadrunner Flight Test
cd /d "%~dp0"

echo.
echo  ========================================
echo    ROADRUNNER FLIGHT TEST  v5.0.0
echo  ========================================
echo.
echo  Starting server...
echo  UI will open at http://localhost:18890
echo  Press Ctrl+C to stop.
echo.

python ws_server.py --sitl --open
