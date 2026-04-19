@echo off
REM ============================================================================
REM  Roadrunner Web GUI — Headed V&V Launcher
REM  Runs a Chromium window you WATCH driving the full test flow.
REM
REM  What it does:
REM    1. Checks Python + Node are installed
REM    2. Installs Playwright (first run only)
REM    3. Builds the React frontend
REM    4. Starts ws_server.py with --sitl (auto-launches SIM vehicles)
REM    5. Opens a Chrome window and drives the full IBIT cycle
REM    6. Verifies all 7 bug fixes visually
REM    7. Cleans up
REM ============================================================================

setlocal EnableDelayedExpansion

set "PROJECT_ROOT=%~dp0.."
set "VV_DIR=%~dp0"
set "PYTHON=python"
set "WS_PORT=18889"
set "HTTP_PORT=18890"

echo.
echo ============================================================================
echo   Roadrunner Web GUI - Headed V^&V
echo   Full end-to-end verification of all 7 bug fixes
echo ============================================================================
echo.

REM --- Check Python ---------------------------------------------------------
where %PYTHON% >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+ and add to PATH.
    exit /b 1
)

REM --- Check Node -----------------------------------------------------------
where node >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Node.js not found. Install Node 18+ from https://nodejs.org
    exit /b 1
)

REM --- Kill any leftover backend from a previous run -------------------------
echo [1/6] Cleaning up any leftover backend processes...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%WS_PORT%" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>nul
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%HTTP_PORT%" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>nul
)
timeout /t 2 /nobreak >nul

REM --- Install Playwright on first run ---------------------------------------
if not exist "%VV_DIR%node_modules" (
    echo [2/6] Installing Playwright (first-run only)...
    pushd "%VV_DIR%"
    call npm install
    if errorlevel 1 (
        echo [ERROR] npm install failed.
        popd
        exit /b 1
    )
    call npx playwright install chromium
    if errorlevel 1 (
        echo [ERROR] Playwright browser install failed.
        popd
        exit /b 1
    )
    popd
) else (
    echo [2/6] Playwright already installed.
)

REM --- Build the React frontend ----------------------------------------------
echo [3/6] Building React frontend...
pushd "%PROJECT_ROOT%\web"
call npm run build
if errorlevel 1 (
    echo [ERROR] Frontend build failed.
    popd
    exit /b 1
)
popd

REM --- Start the backend with SITL -------------------------------------------
echo [4/6] Starting ws_server.py --sitl (backend + SITL sims)...
pushd "%PROJECT_ROOT%"
start "RR-WS-Server-VV" /MIN cmd /c "%PYTHON% ws_server.py --sitl > vv_backend.log 2>&1"
popd

REM --- Wait for the backend to be ready --------------------------------------
echo     Waiting for backend (max 20s)...
set /a counter=0
:wait_loop
timeout /t 1 /nobreak >nul
set /a counter+=1
netstat -ano | findstr ":%HTTP_PORT%" | findstr "LISTENING" >nul
if not errorlevel 1 goto backend_ready
if %counter% geq 20 (
    echo [ERROR] Backend did not start within 20s. Check vv_backend.log.
    exit /b 1
)
goto wait_loop

:backend_ready
echo     Backend ready on http://localhost:%HTTP_PORT%
timeout /t 3 /nobreak >nul

REM --- Run the Playwright test -----------------------------------------------
echo [5/6] Launching headed Chrome and running V^&V test...
echo     ^(A browser window will open — watch it drive the test^)
echo.
pushd "%VV_DIR%"
call npm run test:headed
set TEST_RESULT=%errorlevel%
popd

REM --- Stop the backend ------------------------------------------------------
echo.
echo [6/6] Stopping backend...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%WS_PORT%" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>nul
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%HTTP_PORT%" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>nul
)

REM --- Report ----------------------------------------------------------------
echo.
echo ============================================================================
if %TEST_RESULT% equ 0 (
    echo   V^&V RESULT: PASS
    echo   All 7 bug fixes verified in the live browser.
) else (
    echo   V^&V RESULT: FAIL
    echo   See the HTML report at tests\vv\playwright-report\index.html
)
echo ============================================================================
echo.

if exist "%VV_DIR%playwright-report\index.html" (
    echo Report: %VV_DIR%playwright-report\index.html
    if %TEST_RESULT% neq 0 start "" "%VV_DIR%playwright-report\index.html"
)

exit /b %TEST_RESULT%
