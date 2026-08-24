# PyInstaller spec for the Ripped Ripper desktop GUI.
#
# Built by .github/workflows/build-installers.yml on both macOS and Windows
# runners — a Windows .exe can't be produced from macOS (or vice versa), so
# each OS builds its own artifact from this same spec.
#
# ffmpeg: fetched as a *static* build by the workflow before this runs and
# placed in packaging/ffmpeg_bin/. Homebrew's ffmpeg links ~78 dylibs by
# absolute /opt/homebrew path, so it can't be shipped to machines without
# Homebrew — a static build is self-contained.

import sys
from pathlib import Path

spec_dir = Path(SPECPATH)
repo_dir = spec_dir.parent

# ffmpeg binaries staged by the workflow (empty on a local build without them,
# in which case the app falls back to PATH — see find_ffmpeg()).
ffmpeg_dir = spec_dir / "ffmpeg_bin"
binaries = []
if ffmpeg_dir.is_dir():
    for entry in ffmpeg_dir.iterdir():
        if entry.is_file():
            binaries.append((str(entry), "."))

a = Analysis(
    [str(repo_dir / "ripper_gui.py")],
    pathex=[str(repo_dir)],
    binaries=binaries,
    datas=[],
    # spotdl and ytmusicapi pull several submodules dynamically, which
    # PyInstaller's static analysis doesn't always follow.
    hiddenimports=[
        "spotdl",
        "spotdl.types.song",
        "spotdl.utils.config",
        "spotdl.utils.spotify",
        "spotdl.providers.audio",
        "spotdl.providers.lyrics",
        "ytmusicapi",
        "yt_dlp",
        "yt_dlp.extractor",
        "yt_dlp.postprocessor",
    ],
    hookspath=[],
    runtime_hooks=[],
    # Trim heavyweight things nothing in this app uses. PyQt6 alone would
    # otherwise pull in WebEngine/Quick and add hundreds of MB.
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "PyQt6.QtWebEngineCore",
        "PyQt6.QtWebEngineWidgets",
        "PyQt6.QtQuick",
        "PyQt6.QtQml",
        "PyQt6.Qt3DCore",
        "PyQt6.QtMultimedia",
        "PyQt6.QtBluetooth",
        "PyQt6.QtDesigner",
        "PyQt6.QtTest",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RippedRipper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # GUI app: no terminal window on launch
    icon=str(repo_dir / "assets" / "icon.ico") if sys.platform == "win32"
         else str(repo_dir / "assets" / "icon.icns"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="RippedRipper",
)

# macOS: wrap the collected output in a proper .app bundle so it behaves like
# a real application (Dock icon, Finder double-click) rather than a loose
# executable in a folder.
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Ripped Ripper.app",
        icon=str(repo_dir / "assets" / "icon.icns"),
        bundle_identifier="com.rippedripper.app",
        info_plist={
            "CFBundleName": "Ripped Ripper",
            "CFBundleDisplayName": "Ripped Ripper",
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "1.0.0",
            "NSHighResolutionCapable": True,
            # Qt apps must not be treated as background-only
            "LSBackgroundOnly": False,
        },
    )
