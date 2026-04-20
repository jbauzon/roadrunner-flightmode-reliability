@echo off
REM Captures screenshots of the web GUI for documentation.
REM Requires: Node.js, npm, and the server running (start.bat --sitl).
REM
REM Usage:
REM   1. In one terminal: start.bat --sitl
REM   2. In another terminal: scripts\capture_screenshots.bat
REM
REM Outputs PNGs to docs\images\

cd /d "%~dp0\.."

if not exist "docs\images" mkdir "docs\images"

REM Check if server is running
powershell -Command "try { (New-Object Net.Sockets.TcpClient('localhost', 18890)).Close(); exit 0 } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Server not running. Start it first:
    echo         start.bat --sitl
    exit /b 1
)

echo Installing Playwright for screenshot capture...
cd scripts
if not exist "node_modules" (
    call npm init -y >nul 2>&1
    call npm install playwright >nul 2>&1
    call npx playwright install chromium >nul 2>&1
)

echo Capturing screenshots...
node -e "
const { chromium } = require('playwright');
const path = require('path');
const imgDir = path.join(__dirname, '..', 'docs', 'images');

(async () => {
    const browser = await chromium.launch({ headless: false });
    const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });

    // 01: Initial state
    console.log('  01: Initial state...');
    await page.goto('http://localhost:18890');
    await page.waitForTimeout(4000);
    await page.screenshot({ path: path.join(imgDir, '01_initial_state.png') });

    // 02: Debug Mode
    console.log('  02: Debug Mode...');
    const debugTab = page.locator('text=Debug').first();
    if (await debugTab.isVisible({ timeout: 3000 })) {
        await debugTab.click();
        await page.waitForTimeout(2000);
    }
    await page.screenshot({ path: path.join(imgDir, '02_debug_mode.png') });

    // 03: Back to Test Mode with config
    console.log('  03: Test config...');
    const testTab = page.locator('text=Test').first();
    if (await testTab.isVisible({ timeout: 3000 })) {
        await testTab.click();
        await page.waitForTimeout(2000);
    }
    await page.screenshot({ path: path.join(imgDir, '03_test_config.png') });

    // 04: Start IBIT and capture during test
    console.log('  04: Starting IBIT batch...');
    const startBtn = page.locator('button:has-text(\"Start\")').first();
    if (await startBtn.isEnabled({ timeout: 3000 })) {
        await startBtn.click();
    }
    console.log('  Waiting 25s for IBIT to be in progress...');
    await page.waitForTimeout(25000);
    await page.screenshot({ path: path.join(imgDir, '04_ibit_running.png') });

    // 05: Wait for result
    console.log('  05: Waiting 40s for IBIT completion...');
    await page.waitForTimeout(40000);
    await page.screenshot({ path: path.join(imgDir, '05_ibit_result.png') });

    // 06: Stop and capture final state
    console.log('  06: Stopping...');
    const stopBtn = page.locator('button:has-text(\"Stop\")').first();
    if (await stopBtn.isEnabled({ timeout: 2000 })) {
        await stopBtn.click();
    }
    await page.waitForTimeout(3000);
    await page.screenshot({ path: path.join(imgDir, '06_stopped.png') });

    // 07: Switch to Playback mode
    console.log('  07: Playback config...');
    const pbBtn = page.locator('button:has-text(\"Playback\")').first();
    if (await pbBtn.isVisible({ timeout: 2000 })) {
        await pbBtn.click();
        await page.waitForTimeout(1500);
    }
    await page.screenshot({ path: path.join(imgDir, '07_playback_config.png') });

    await browser.close();
    console.log('');
    console.log('Screenshots saved to docs\\images\\');
})();
"

cd ..
echo.
echo Screenshots:
dir /b docs\images\*.png 2>nul
