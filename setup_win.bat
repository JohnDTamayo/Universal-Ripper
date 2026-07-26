@echo off
REM ──────────────────────────────────────────────────────────────────────────
REM  Ripped Ripper — First-Time Setup & Desktop Installer (Windows)
REM  Double-click to set up the Python environment, dependencies, and Desktop shortcut.
REM ──────────────────────────────────────────────────────────────────────────

title Ripped Ripper Setup
cd /d "%~dp0"
set "REPO_DIR=%~dp0"
if "%REPO_DIR:~-1%"=="\" set "REPO_DIR=%REPO_DIR:~0,-1%"

echo.
echo ==================================================
echo   Ripped Ripper — Initial Setup ^& Installer
echo ==================================================
echo.

REM 1. Check for Python 3
set PYTHON=
where python >nul 2>&1
if %errorlevel%==0 (
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
    echo Please install Python 3 from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('%PYTHON% --version 2^>^&1') do echo [OK] Using %%i

REM 2. Check for ffmpeg
where ffmpeg >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [WARNING] ffmpeg is not installed.
    echo   Audio conversion requires ffmpeg.
    echo   Download from: https://ffmpeg.org/download.html
    echo.
)

REM 3. Create virtual environment if needed
if not exist "venv" (
    echo [SETUP] Creating virtual environment...
    %PYTHON% -m venv venv
    echo [OK] Virtual environment created.
)

REM 4. Activate venv & install dependencies
call venv\Scripts\activate.bat
echo [SETUP] Installing dependencies...
python -m pip install --upgrade pip -q
if exist "requirements.txt" (
    pip install -r requirements.txt -q
)
if exist "requirements_gui.txt" (
    pip install -r requirements_gui.txt -q
)
echo. > venv\.deps_installed
echo [OK] Dependencies installed.

REM 5. Generate icon.ico from assets\icon.png
echo [SETUP] Generating app icon...
python -c "from PIL import Image; import os; img = Image.open('assets/icon.png'); img.save('assets/icon.ico', format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])" >nul 2>&1

REM 6. Create Desktop shortcut "Ripped Ripper.lnk" using PowerShell
echo [SETUP] Creating Desktop Shortcut 'Ripped Ripper'...
powershell -Command "$s=(New-Object -COM WScript.Shell).CreateShortcut([System.IO.Path]::Combine([Environment]::GetFolderPath('Desktop'), 'Ripped Ripper.lnk')); $s.TargetPath='%REPO_DIR%\launch_gui.bat'; $s.WorkingDirectory='%REPO_DIR%'; $s.IconLocation='%REPO_DIR%\assets\icon.ico'; $s.Save()"

echo.
echo ==================================================
echo   Setup Complete!
echo   Desktop Shortcut Created: 'Ripped Ripper' on your Desktop
echo ==================================================
echo.
pause
