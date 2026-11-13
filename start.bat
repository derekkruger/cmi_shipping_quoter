@echo off
REM CMI Shipping Quoter - Windows launcher. Double-click to run.
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (set PY=py -3) else (set PY=python)

if not exist ".venv\Scripts\python.exe" (
    echo First run: creating virtual environment...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo.
        echo Python 3.10+ is required. Install it from https://www.python.org/downloads/
        echo and tick "Add python.exe to PATH" during setup.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

".venv\Scripts\python.exe" app.py
pause
