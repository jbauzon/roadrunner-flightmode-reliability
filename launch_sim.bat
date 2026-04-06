@echo off
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "%~dp0"
python run_sim.py %*
if errorlevel 1 (
    echo.
    echo [ERROR] run_sim.py exited with error code %errorlevel%
    echo.
)
pause
