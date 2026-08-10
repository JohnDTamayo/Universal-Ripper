#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# Ripped Ripper — Quick Launcher (macOS)
# Double-click to instantly launch the desktop GUI.
# ──────────────────────────────────────────────────────────────────────────────

set -e

cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
    echo "⚠️ Virtual environment not found."
    echo "   Please run ./setup_mac.command first to complete initial setup."
    read -p "Press Enter to exit..."
    exit 1
fi

# Make sure Homebrew tools (ffmpeg) are reachable even if the shell profile
# hasn't set them up, matching what the Desktop .app launcher does.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

if ! command -v ffmpeg &>/dev/null; then
    echo "⚠️  ffmpeg not found — audio conversion may fail. Install with: brew install ffmpeg"
fi

source venv/bin/activate
echo "🚀 Launching Ripped Ripper GUI..."
python ripper_gui.py
