@echo off
rem VoxAgent — double-click = the web portal opens in your browser.
rem The server runs minimized in the background; close its window to stop.
rem Other modes from a terminal:  run.bat text | voice | live | live-hd | web
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo First run: creating virtual environment and installing dependencies...
    python -m venv .venv
    ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
)

set "MODE=%~1"
if "%MODE%"=="" set "MODE=web"

if "%MODE%"=="web" (
    start "VoxAgent server" /min ".venv\Scripts\python.exe" server.py
    exit /b
)
if "%MODE%"=="text"    ".venv\Scripts\python.exe" main.py & goto end
if "%MODE%"=="voice"   ".venv\Scripts\python.exe" voice_main.py & goto end
if "%MODE%"=="live"    ".venv\Scripts\python.exe" live_main.py & goto end
if "%MODE%"=="live-hd" ".venv\Scripts\python.exe" live_main.py --half-duplex & goto end

echo Unknown option "%MODE%" - use web, text, voice, live, or live-hd.
:end
pause
