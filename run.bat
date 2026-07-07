@echo off
rem VoxAgent launcher. Double-click for the menu, or run with an argument:
rem     run.bat text      - text chat (main.py)
rem     run.bat voice     - push-to-talk voice (voice_main.py)
rem     run.bat live      - real-time call, wear headphones (live_main.py)
rem     run.bat live-hd   - real-time call without headphones (--half-duplex)
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo First run: creating virtual environment and installing dependencies...
    python -m venv .venv
    ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
)

set "MODE=%~1"
if not "%MODE%"=="" goto run

echo.
echo    === VoxAgent ===
echo    1. Text chat
echo    2. Push-to-talk voice
echo    3. Live call  (wear headphones)
echo    4. Live call  (no headphones / half-duplex)
echo    5. Web page   (opens in your browser)
echo.
set /p MODE=Pick 1-5 [default 5]:
if "%MODE%"=="" set "MODE=5"

:run
if "%MODE%"=="1" set "MODE=text"
if "%MODE%"=="2" set "MODE=voice"
if "%MODE%"=="3" set "MODE=live"
if "%MODE%"=="4" set "MODE=live-hd"
if "%MODE%"=="5" set "MODE=web"

if "%MODE%"=="text"    ".venv\Scripts\python.exe" main.py & goto end
if "%MODE%"=="voice"   ".venv\Scripts\python.exe" voice_main.py & goto end
if "%MODE%"=="live"    ".venv\Scripts\python.exe" live_main.py & goto end
if "%MODE%"=="live-hd" ".venv\Scripts\python.exe" live_main.py --half-duplex & goto end
if "%MODE%"=="web"     ".venv\Scripts\python.exe" server.py & goto end

echo Unknown option "%MODE%" - use text, voice, live, live-hd, or web.

:end
rem Keep the window open when double-clicked so errors stay readable.
pause
