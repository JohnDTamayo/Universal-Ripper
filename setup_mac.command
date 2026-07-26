#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# Ripped Ripper — First-Time Setup & Desktop Installer (macOS)
# Double-click to set up the Python environment, dependencies, and Desktop shortcut.
# ──────────────────────────────────────────────────────────────────────────────

set -e

# Change directory to the repository root
cd "$(dirname "$0")"
REPO_DIR="$(pwd)"

echo "=================================================="
echo "  Ripped Ripper — Initial Setup & Installer"
echo "=================================================="
echo ""

# 1. Check for Python 3
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
    echo "❌ Error: Python 3 is required but not found."
    echo "   Please install Python 3 from https://www.python.org/ or via Homebrew: brew install python"
    read -p "Press Enter to exit..."
    exit 1
fi

echo "✅ Python binary: $($PYTHON --version)"

# 2. Check for ffmpeg
if ! command -v ffmpeg &>/dev/null; then
    echo "⚠️  Warning: ffmpeg is not installed on your system."
    echo "   Audio conversion requires ffmpeg. Install via: brew install ffmpeg"
fi

# 3. Create virtual environment if missing
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    $PYTHON -m venv venv
fi

# 4. Activate virtual environment & install requirements
source venv/bin/activate
echo "📥 Installing/updating Python dependencies..."
pip install --upgrade pip -q
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt -q
fi
if [ -f "requirements_gui.txt" ]; then
    pip install -r requirements_gui.txt -q
fi
touch venv/.deps_installed
echo "✅ Dependencies successfully installed."

# 5. Generate icon.icns & icon.ico from assets/icon.png using Pillow
echo "🎨 Generating app icons..."
python -c "
from PIL import Image
import os
icon_png = os.path.join('$REPO_DIR', 'assets', 'icon.png')
if os.path.exists(icon_png):
    img = Image.open(icon_png)
    img.save(os.path.join('$REPO_DIR', 'assets', 'icon.ico'), format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
    try:
        img.save(os.path.join('$REPO_DIR', 'assets', 'icon.icns'), format='ICNS')
    except Exception as e:
        pass
" 2>/dev/null || true

# 6. Create macOS Application Bundle on Desktop ("Ripped Ripper.app")
DESKTOP_APP="$HOME/Desktop/Ripped Ripper.app"
echo "🖥️  Creating Desktop Shortcut: 'Ripped Ripper.app'..."

rm -rf "$DESKTOP_APP"
mkdir -p "$DESKTOP_APP/Contents/MacOS"
mkdir -p "$DESKTOP_APP/Contents/Resources"

# Copy ICNS icon
if [ -f "assets/icon.icns" ]; then
    cp "assets/icon.icns" "$DESKTOP_APP/Contents/Resources/AppIcon.icns"
fi

# Create Info.plist
cat <<EOF > "$DESKTOP_APP/Contents/Info.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>RippedRipper</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundleIdentifier</key>
    <string>com.rippedripper.app</string>
    <key>CFBundleName</key>
    <string>Ripped Ripper</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
</dict>
</plist>
EOF

# Create executable launcher inside .app bundle
cat <<EOF > "$DESKTOP_APP/Contents/MacOS/RippedRipper"
#!/bin/bash
cd "$REPO_DIR"
source venv/bin/activate
exec python ripper_gui.py
EOF

chmod +x "$DESKTOP_APP/Contents/MacOS/RippedRipper"
touch "$DESKTOP_APP"

echo ""
echo "=================================================="
echo "✨ Setup complete!"
echo "   Desktop App Created: 'Ripped Ripper' on your Desktop"
echo "=================================================="
echo ""
read -p "Press Enter to exit..."
