@echo off
REM ──────────────────────────────────────────────────────────────────────────
REM  Ripped Ripper — Quick Launcher (Windows)
REM  Double-click to instantly launch the desktop GUI.
REM ──────────────────────────────────────────────────────────────────────────

title Ripped Ripper
cd /d "%~dp0"

if not exist "venv" (
    echo [ERROR] Virtual environment not found.
    echo Please run setup_win.bat first to complete initial setup.
    echo.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
echo Launching Ripped Ripper GUI...
python ripper_gui.py
