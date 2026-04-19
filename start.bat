@echo off
title Roadrunner Flight Test v5.0.0
cd /d "%~dp0"

echo.
echo  ========================================
echo    ROADRUNNER FLIGHT TEST  v5.0.0
echo  ========================================
echo.

:: Find Python
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo  ERROR: Python not found on PATH.
    echo  Install Python 3.11+ from python.org
    pause
    exit /b 1
)

:: Kill any leftover backend from a previous run (port 18889/18890)
echo  Cleaning up any previous server...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":18889" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":18890" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul

:: Check for --sitl flag
set SITL_ARG=
if /I "%~1"=="--sitl" set SITL_ARG=--sitl
if /I "%~1"=="-s"     set SITL_ARG=--sitl

if defined SITL_ARG (
    echo  Mode: SITL simulation ^(no hardware required^)
) else (
    echo  Mode: Hardware ^(pass --sitl to run with simulator^)
)
echo.
echo  Starting server on http://localhost:18890
echo  Press Ctrl+C in this window to stop.
echo.

:: Open browser after 4 seconds (background)
start "" /B cmd /c "timeout /t 4 /nobreak >nul && start http://localhost:18890"

:: Run the server in the FOREGROUND so Ctrl+C cleanly stops it
:: and closing this window kills the server.
python ws_server.py %SITL_ARG%

:: Exit code from the server
set SERVER_EXIT=%ERRORLEVEL%

echo.
if %SERVER_EXIT% neq 0 (
    echo  Server exited with code %SERVER_EXIT%.
    pause
)
exit /b %SERVER_EXIT%
