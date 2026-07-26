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

source venv/bin/activate
echo "🚀 Launching Ripped Ripper GUI..."
python ripper_gui.py
