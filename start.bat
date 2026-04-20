@echo off
title Roadrunner Flight Test v5.0.0
cd /d "%~dp0"

REM --- Auto-install if needed ---------------------------------
python -c "import rr_test, pymavlink, websockets" >nul 2>&1
if errorlevel 1 (
    echo First run - installing dependencies...
    call scripts\install.bat
    if errorlevel 1 exit /b 1
    echo.
)

if not exist "web\dist\index.html" (
    echo Building web frontend...
    call scripts\install.bat
    if errorlevel 1 exit /b 1
    echo.
)

REM --- Kill leftover processes --------------------------------
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":18889" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":18890" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul

REM --- Parse flags --------------------------------------------
set EXTRA_ARGS=
if /I "%~1"=="--sitl" set EXTRA_ARGS=--sitl
if /I "%~1"=="-s"     set EXTRA_ARGS=--sitl

echo.
echo  ========================================
echo    ROADRUNNER FLIGHT TEST  v5.0.0
echo  ========================================
echo   URL:  http://localhost:18890
echo   Press Ctrl+C to stop the server.
echo  ========================================
echo.

REM --- Open browser -------------------------------------------
start "" /B cmd /c "timeout /t 4 /nobreak >nul && start http://localhost:18890"

REM --- Run server ---------------------------------------------
python ws_server.py %EXTRA_ARGS%
set EXIT_CODE=%ERRORLEVEL%

echo.
if %EXIT_CODE% neq 0 (
    echo Server exited with code %EXIT_CODE%.
    pause
)
exit /b %EXIT_CODE%
