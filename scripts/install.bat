@echo off
REM Fresh-computer installer for Roadrunner Flight Mode IBIT Test System.
REM Creates a venv, installs Python deps, and builds the web frontend.

setlocal EnableDelayedExpansion
cd /d "%~dp0\.."

echo.
echo ============================================================
echo   Roadrunner Flight Test - Installer
echo ============================================================
echo.

REM --- Check Python -------------------------------------------------------
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found on PATH.
    echo         Install Python 3.11 or newer from https://www.python.org/downloads/
    echo         Be sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo [OK]    Python %PY_VER% detected

REM --- Create venv --------------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo [INFO]  Creating virtual environment .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

REM --- Install Python deps (verbose: show progress and errors) ------------
echo [INFO]  Upgrading pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
    echo [ERROR] Failed to upgrade pip.
    pause
    exit /b 1
)

echo [INFO]  Installing Roadrunner test package and dependencies...
echo         (This needs internet access; first run takes ~1-2 minutes.)
".venv\Scripts\python.exe" -m pip install -e ".[hardware]"
if errorlevel 1 (
    echo.
    echo [ERROR] pip install failed.
    echo         Common causes:
    echo         - No internet connection
    echo         - Corporate proxy blocking PyPI
    echo         - pyproject.toml syntax error
    pause
    exit /b 1
)
echo [OK]    Python package installed

REM --- Verify the package actually imports --------------------------------
".venv\Scripts\python.exe" -c "import rr_test; import pymavlink; import websockets" 2>nul
if errorlevel 1 (
    echo [ERROR] Import check failed after install.  Something went wrong.
    echo         Try running: .venv\Scripts\python.exe -c "import rr_test"
    echo         and fix the error shown.
    pause
    exit /b 1
)
echo [OK]    Core imports verified (rr_test, pymavlink, websockets)

REM --- Check NI-DAQmx (optional, for real hardware) -----------------------
".venv\Scripts\python.exe" -c "import nidaqmx" >nul 2>&1
if errorlevel 1 (
    echo [WARN]  NI-DAQmx Python binding not importable.
    echo         SITL mode works without it: start.bat --sitl
    echo         For real hardware, install NI-DAQmx driver from:
    echo         https://www.ni.com/en-us/support/downloads/drivers/download.ni-daq-mx.html
) else (
    echo [OK]    NI-DAQmx Python binding imports
)

REM --- Check Node.js + build frontend -------------------------------------
where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found on PATH.
    echo         Install Node.js 20 LTS from https://nodejs.org/
    echo         The web frontend cannot be built without Node.
    pause
    exit /b 1
)

if not exist "web\dist\index.html" (
    echo [INFO]  Building web frontend ^(may take 30-60 seconds^)...
    pushd web
    call npm install
    if errorlevel 1 (
        echo [ERROR] npm install failed.  Check internet / proxy.
        popd
        pause
        exit /b 1
    )
    call npm run build
    if errorlevel 1 (
        echo [ERROR] npm run build failed.
        popd
        pause
        exit /b 1
    )
    popd
)
echo [OK]    Web frontend built ^(web\dist\^)

echo.
echo ============================================================
echo   Installation complete.
echo.
echo   Run:  start.bat          (production, needs NI-DAQmx)
echo   Run:  start.bat --sitl   (simulator, no hardware)
echo ============================================================
exit /b 0
