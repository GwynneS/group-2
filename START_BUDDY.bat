@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" start_buddy.py
  goto finished
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3 start_buddy.py
  goto finished
)
where python >nul 2>nul
if not errorlevel 1 (
  python start_buddy.py
  goto finished
)
echo Python was not found. Install Python 3.11 or newer, then try again.
echo Read START_HERE.md for setup and troubleshooting.
:finished
echo.
echo If an error appeared above, take a screenshot of it before closing.
pause
