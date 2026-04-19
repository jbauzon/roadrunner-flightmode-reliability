@echo off
title Roadrunner Flight Test v5.0.0
cd /d "%~dp0"

REM --- Auto-install on first run or when core files missing -------
if not exist ".venv\Scripts\python.exe" (
    echo First run detected - installing...
    call scripts\install.bat
    if errorlevel 1 exit /b 1
    echo.
)

if not exist "web\dist\index.html" (
    echo Web frontend missing - building...
    call scripts\install.bat
    if errorlevel 1 exit /b 1
    echo.
)

REM --- Verify the venv Python actually has the deps ---------------
".venv\Scripts\python.exe" -c "import rr_test, pymavlink, websockets" >nul 2>&1
if errorlevel 1 (
    echo Dependencies not fully installed - reinstalling...
    call scripts\install.bat
    if errorlevel 1 exit /b 1
    echo.
)

REM --- Clean up any leftover backend ------------------------------
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":18889" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":18890" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul

REM --- Parse mode --------------------------------------------------
set SITL_ARG=
if /I "%~1"=="--sitl" set SITL_ARG=--sitl
if /I "%~1"=="-s"     set SITL_ARG=--sitl

echo.
echo  ========================================
echo    ROADRUNNER FLIGHT TEST  v5.0.0
echo  ========================================
if defined SITL_ARG (
    echo   Mode: SITL simulation
) else (
    echo   Mode: Hardware ^(pass --sitl to use simulator^)
)
echo   URL:  http://localhost:18890
echo   Ctrl+C in this window to stop.
echo  ========================================
echo.

REM --- Open browser after 4 seconds -------------------------------
start "" /B cmd /c "timeout /t 4 /nobreak >nul && start http://localhost:18890"

REM --- Run the server directly with the venv Python ---------------
".venv\Scripts\python.exe" ws_server.py %SITL_ARG%
set SERVER_EXIT=%ERRORLEVEL%

echo.
if %SERVER_EXIT% neq 0 (
    echo Server exited with code %SERVER_EXIT%.
    pause
)
exit /b %SERVER_EXIT%
