@echo off
setlocal
title SkyCast AI
rem ============================================================
rem  SkyCast AI - one-click launcher
rem  * Works from ANY directory (uses this file's own folder)
rem  * Auto-picks a free port (5000 belongs to another app)
rem  * Opens the browser automatically
rem ============================================================

rem cd to the folder that contains THIS script
cd /d "%~dp0"

rem ---- find the first free browser-safe port ----
set "PORT=8080"
for %%P in (8080 8000 3000 5001 5050 8060 8099) do (
    powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort %%P -State Listen -ErrorAction SilentlyContinue) { exit 1 } else { exit 0 }" >nul 2>&1
    if not errorlevel 1 (
        set "PORT=%%P"
        goto :portfound
    )
)
:portfound

set "SKYCAST_PORT=%PORT%"

echo ============================================================
echo   SkyCast AI  ->  http://127.0.0.1:%PORT%
echo   Press Ctrl+C to stop the server.
echo ============================================================

rem open the browser (after the server has 4s to boot)
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 4; Start-Process 'http://127.0.0.1:%PORT%'"

python app.py
pause