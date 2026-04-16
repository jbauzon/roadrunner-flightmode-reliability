@echo off
title Roadrunner Flight Test v5.0.0
cd /d "%~dp0"

echo.
echo  ╔════════════════════════════════════════╗
echo  ║   ROADRUNNER FLIGHT TEST  v5.0.0       ║
echo  ╚════════════════════════════════════════╝
echo.

:: Find Python
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo  ERROR: Python not found on PATH.
    echo  Install Python 3.11+ from python.org
    pause
    exit /b 1
)

echo  Starting server...
echo  Press Ctrl+C to stop.
echo.

:: Start server and open browser after 3 seconds
start /b python ws_server.py
timeout /t 4 /nobreak >nul
start http://localhost:18890

:: Keep the window open so the server stays running
echo  Server running at http://localhost:18890
echo  Close this window to stop the server.
echo.
python ws_server.py
