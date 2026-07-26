#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# Ripper GUI Launcher (macOS)
# Double-click this file to set up and launch the Ripper GUI.
# It will install Python dependencies on first run, then launch the app.
# ──────────────────────────────────────────────────────────────────────────────

set -e

# cd to the directory where this script lives (the project root)
cd "$(dirname "$0")"

echo ""
echo "=========================================="
echo "  Ripper GUI Launcher"
echo "=========================================="
echo ""

# ── 1. Check for Python 3 ────────────────────────────────────────────────────
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        version=$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
        major=$(echo "$version" | cut -d. -f1)
        if [ "$major" -ge 3 ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "[ERROR] Python 3 is required but not found."
    echo ""
    echo "Install it from: https://www.python.org/downloads/"
    echo "  or via Homebrew:  brew install python"
    echo ""
    read -p "Press Enter to close..."
    exit 1
fi

echo "[OK] Using $($PYTHON --version)"

# ── 2. Check for ffmpeg ──────────────────────────────────────────────────────
if ! command -v ffmpeg &>/dev/null; then
    echo ""
    echo "[WARNING] ffmpeg is not installed."
    echo "  Audio conversion requires ffmpeg."
    echo "  Install via:  brew install ffmpeg"
    echo ""
fi

# ── 3. Create virtual environment if needed ──────────────────────────────────
if [ ! -d "venv" ]; then
    echo "[SETUP] Creating virtual environment..."
    $PYTHON -m venv venv
    echo "[OK] Virtual environment created."
fi

# ── 4. Activate venv ─────────────────────────────────────────────────────────
source venv/bin/activate
echo "[OK] Virtual environment activated."

# ── 5. Install / update dependencies ─────────────────────────────────────────
# Use a stamp file to avoid re-installing every launch
STAMP="venv/.deps_installed"
REQ="requirements_gui.txt"

if [ ! -f "$STAMP" ] || [ "$REQ" -nt "$STAMP" ]; then
    echo "[SETUP] Installing dependencies (first run or requirements changed)..."
    pip install --upgrade pip -q
    pip install -r "$REQ" -q
    touch "$STAMP"
    echo "[OK] Dependencies installed."
else
    echo "[OK] Dependencies up to date."
fi

# ── 6. Launch ─────────────────────────────────────────────────────────────────
echo ""
echo "Launching Ripper GUI..."
echo ""
python ripper_gui.py

# Keep terminal open if the app crashes
echo ""
echo "Ripper GUI exited."
read -p "Press Enter to close this window..."
