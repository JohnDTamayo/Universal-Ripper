@echo off
REM ──────────────────────────────────────────────────────────────────────────
REM  Ripper GUI Launcher (Windows)
REM  Double-click this file to set up and launch the Ripper GUI.
REM  It will install Python dependencies on first run, then launch the app.
REM ──────────────────────────────────────────────────────────────────────────

title Ripper GUI Launcher
cd /d "%~dp0"

echo.
echo ==========================================
echo   Ripper GUI Launcher
echo ==========================================
echo.

REM ── 1. Check for Python 3 ──────────────────────────────────────────────────
set PYTHON=
where python >nul 2>&1
if %errorlevel%==0 (
    for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
    set PYTHON=python
)
if not defined PYTHON (
    where python3 >nul 2>&1
    if %errorlevel%==0 (
        set PYTHON=python3
    )
)

if not defined PYTHON (
    echo [ERROR] Python 3 is required but not found.
    echo.
    echo Install it from: https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('%PYTHON% --version 2^>^&1') do echo [OK] Using %%i

REM ── 2. Check for ffmpeg ────────────────────────────────────────────────────
where ffmpeg >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [WARNING] ffmpeg is not installed.
    echo   Audio conversion requires ffmpeg.
    echo   Download from: https://ffmpeg.org/download.html
    echo.
)

REM ── 3. Create virtual environment if needed ────────────────────────────────
if not exist "venv" (
    echo [SETUP] Creating virtual environment...
    %PYTHON% -m venv venv
    echo [OK] Virtual environment created.
)

REM ── 4. Activate venv ───────────────────────────────────────────────────────
call venv\Scripts\activate.bat
echo [OK] Virtual environment activated.

REM ── 5. Install / update dependencies ───────────────────────────────────────
if not exist "venv\.deps_installed" goto :install_deps

REM Check if requirements file is newer than stamp
for %%A in (requirements_gui.txt) do set REQ_DATE=%%~tA
for %%A in (venv\.deps_installed) do set STAMP_DATE=%%~tA

REM Simple check: if stamp exists, skip unless user deletes it
if exist "venv\.deps_installed" (
    echo [OK] Dependencies up to date.
    goto :launch
)

:install_deps
echo [SETUP] Installing dependencies (first run or requirements changed)...
pip install --upgrade pip -q
pip install -r requirements_gui.txt -q
echo. > venv\.deps_installed
echo [OK] Dependencies installed.

:launch
REM ── 6. Launch ──────────────────────────────────────────────────────────────
echo.
echo Launching Ripper GUI...
echo.
python ripper_gui.py

echo.
echo Ripper GUI exited.
pause
