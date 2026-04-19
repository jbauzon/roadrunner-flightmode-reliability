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
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo [OK]    Python %PY_VER% detected

REM --- Create venv --------------------------------------------------------
if not exist ".venv" (
    echo [INFO]  Creating virtual environment .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        exit /b 1
    )
)

call .venv\Scripts\activate.bat

REM --- Install Python deps ------------------------------------------------
echo [INFO]  Installing Python dependencies (requires internet) ...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -e ".[hardware]"
if errorlevel 1 (
    echo [ERROR] pip install failed. Check your internet connection.
    exit /b 1
)
echo [OK]    Python dependencies installed

REM --- Check NI-DAQmx (optional, Windows only) ----------------------------
python -c "import nidaqmx" >nul 2>&1
if errorlevel 1 (
    echo [WARN]  NI-DAQmx driver not detected.
    echo         SITL mode works without it: start.bat --sitl
    echo         For real hardware, install NI-DAQmx from
    echo         https://www.ni.com/en-us/support/downloads/drivers/download.ni-daq-mx.html
) else (
    echo [OK]    NI-DAQmx driver detected
)

REM --- Check Node.js + build frontend -------------------------------------
where node >nul 2>&1
if errorlevel 1 (
    echo [WARN]  Node.js not found. Install from https://nodejs.org/ (LTS version)
    echo         The web frontend cannot be built without Node.
    exit /b 1
)
if not exist "web\dist\index.html" (
    echo [INFO]  Building web frontend ...
    pushd web
    call npm install --silent
    if errorlevel 1 (
        echo [ERROR] npm install failed.
        popd
        exit /b 1
    )
    call npm run build
    if errorlevel 1 (
        echo [ERROR] npm run build failed.
        popd
        exit /b 1
    )
    popd
)
echo [OK]    Web frontend built (web\dist\)

echo.
echo ============================================================
echo   Installation complete.
echo.
echo   Run:  start.bat          (production, needs NI-DAQmx)
echo   Run:  start.bat --sitl   (simulator, no hardware)
echo ============================================================
exit /b 0
