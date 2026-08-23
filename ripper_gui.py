#!/usr/bin/env python3
"""
Ripper GUI
──────────
Standalone PyQt6 desktop app for:
  • Search & Rip  — search YouTube Music, download as MP3 / M4A / FLAC / WAV
  • Playlist Ripper — paste a Spotify or Apple Music playlist URL, download all tracks

Dependencies: PyQt6, ytmusicapi, yt-dlp, spotdl
Run: python ripper_gui.py
"""

import re
import sys
import json
import time
import colorsys
import tempfile
import threading
import subprocess
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from string import Template

from PyQt6.QtCore import (
    QObject, QRunnable, QSettings, QThread, QThreadPool,
    Qt, pyqtSignal, QUrl,
)
from PyQt6.QtGui import QFont, QColor, QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QColorDialog, QComboBox, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QProgressBar, QPushButton, QScrollArea,
    QSizePolicy, QSlider, QSpinBox, QTabWidget, QVBoxLayout, QWidget, QCheckBox,
    QTextEdit, QSplitter
)

from ytmusicapi import YTMusic
import yt_dlp

# ─── Constants ───────────────────────────────────────────────────────────────

BASE_DIR    = Path(__file__).parent
SEARCH_DIR  = BASE_DIR / "DJ_Search_Rips"
PLAYLIST_DIR = BASE_DIR / "Playlist_Rips"
MAX_WORKERS = 8

# ── Output formats ───────────────────────────────────────────────────────────
# Everything format-specific lives here: the picker builds itself from this
# table and build_ydl_opts derives its yt-dlp config from it, so adding a
# format is a matter of adding a row.
#
# A note on quality: YouTube Music only serves lossy audio (~129kbps AAC/Opus),
# and that is the ceiling. "m4a" copies that stream through untouched, so it is
# the only option with no re-encode. wav/flac are lossless *containers* holding
# the same lossy audio — they don't recover anything, they just take up more
# room. mp3 re-encodes, costing a little quality for the widest compatibility.
AUDIO_FORMATS: dict[str, dict] = {
    "mp3": {
        "label":    "MP3",
        "hint":     "320 kbps · widest compatibility · ~9 MB/track",
        "codec":    "mp3",
        "quality":  "320",
        "lossless": False,
    },
    "m4a": {
        "label":    "M4A",
        "hint":     "AAC copied as-is · fastest, no re-encode · ~4 MB/track",
        "codec":    "m4a",
        "quality":  "0",       # ignored; the AAC stream is copied as-is
        "lossless": False,
    },
    "flac": {
        "label":    "FLAC",
        "hint":     "Lossless container · ~24 MB/track",
        "codec":    "flac",
        "quality":  "0",
        "lossless": True,
        # ffmpeg defaults to 24-bit here, which makes the FLAC *larger* than a
        # 16-bit WAV for no gain — the source is a decoded lossy stream, so
        # there's no extra depth to preserve.
        "pp_args":  ["-sample_fmt", "s16"],
    },
    "wav": {
        "label":    "WAV",
        "hint":     "Lossless, no metadata support · ~44 MB/track",
        "codec":    "wav",
        "quality":  "0",
        "lossless": True,
    },
}
DEFAULT_AUDIO_FORMAT = "mp3"

# Every format we recognise on disk, used to spot a track that's already been
# ripped in some other format.
KNOWN_AUDIO_EXTS = tuple(AUDIO_FORMATS)

# spotdl's publicly bundled Spotify credentials (from their open-source repo)
SPOTDL_CLIENT_ID     = "5f573c9620494bae87890c0f08a60293"
SPOTDL_CLIENT_SECRET = "212476d9b0f3472eaa762d90b19b0ba8"


# ─── Dependency auto-update ────────────────────────────────────────────────────
#
# yt-dlp, ytmusicapi, and spotdl all wrap unofficial/reverse-engineered APIs
# (YouTube's player internals, YouTube Music's internal API, Spotify's client
# auth) that their providers change without notice — "it worked yesterday"
# breakage that gets fixed by a point release, often within days. A stale
# install is the single most likely reason rips or playlist fetches start
# failing, so each of these is checked against PyPI once a day and upgraded
# automatically when it's safe to.
#
# Deliberately NOT included: PyQt6, fastapi/starlette/uvicorn/jinja2, Pillow.
# None of those are in an adversarial relationship with anything — they don't
# need to chase a moving target, and blindly auto-upgrading them trades one
# kind of silent breakage for another (this is exactly what happened when
# spotdl's fastapi<0.104 pin broke the web dashboard after an unrelated venv
# rebuild).
#
# Two different safety policies are used, matched to how each package can
# actually break us:
#   - yt-dlp and ytmusicapi are bounded by whatever range spotdl itself
#     currently declares for them, read live from spotdl's package metadata.
#     We only use their stable public APIs, so anything within spotdl's own
#     accepted range is safe.
#   - spotdl has no upstream bound in our stack, and we touch one of its
#     undocumented internal methods (see the try/except around
#     SpotdlSong.from_missing_data in _fetch_spotify — deliberately made
#     failure-tolerant for exactly this reason). semver only promises no
#     breaking changes below a major version bump, so spotdl self-limits to
#     the current major version and just logs an advisory beyond that,
#     leaving a major upgrade to a manual decision.

def version_tuple(v: str) -> tuple[int, ...]:
    """
    Parse a dotted version like '2026.8.19' or '4.5.2' into (2026, 8, 19) or
    (4, 5, 2). Good enough for yt-dlp's date-based scheme and everyone else's
    semver — not a general PEP 440 parser (no pre-release/epoch handling,
    which none of these three packages' stable releases need).
    """
    nums = re.findall(r"\d+", v)
    return tuple(int(n) for n in nums) if nums else (0,)


def installed_version(package: str) -> str | None:
    """Installed version of a package, or None if it isn't installed."""
    try:
        import importlib.metadata as md
        return md.version(package)
    except Exception:
        return None


def dependent_version_bounds(
    dependent: str, target: str
) -> tuple[tuple[int, ...] | None, tuple[int, ...] | None]:
    """
    Read `dependent`'s own declared version range for `target` (e.g. spotdl's
    'yt-dlp<2027,>=2026.07.04') from installed package metadata, so we always
    respect whatever the dependent currently requires rather than a bound
    hardcoded here that could go stale the moment spotdl changes its pin.
    Returns (min, max) as tuples; either may be None if there's no such bound,
    or if `dependent` isn't installed / the requirement is unparsable.
    """
    def req_name(req: str) -> str:
        # A requirement string is "name[extras]<specifier>; marker" — the
        # specifier butts directly against the name with no separator when
        # there are no extras (e.g. "ytmusicapi<2,>=1.12.1"), so only a
        # regex on the leading name-ish characters reliably isolates it.
        m = re.match(r"^([A-Za-z0-9_.\-]+)", req.split(";")[0].strip())
        return m.group(1).lower().replace("_", "-") if m else ""

    try:
        import importlib.metadata as md
        target_norm = target.lower().replace("_", "-")
        req = next(
            (r for r in (md.requires(dependent) or []) if req_name(r) == target_norm),
            None,
        )
    except Exception:
        return None, None
    if not req:
        return None, None

    lo = hi = None
    for op, val in re.findall(r"(>=|<=|==|<|>)\s*([0-9][0-9.]*)", req):
        v = version_tuple(val)
        if op in (">=", ">"):
            lo = v
        elif op in ("<=", "<"):
            hi = v
    return lo, hi


def same_major_ceiling(current_version: str) -> tuple[int, ...]:
    """
    Self-imposed ceiling for a package nothing in our stack bounds: allow
    patch/minor updates but stop at the next major version, matching semver's
    only real promise (no breaking changes below a major bump).
    """
    major = version_tuple(current_version)[0]
    return (major + 1,)


@dataclass
class UpdatePolicy:
    package:  str                                          # PyPI package name
    version_getter: object                                 # () -> str | None
    bounds_getter:  object                                  # () -> (lo, hi)


UPDATE_POLICIES = [
    UpdatePolicy(
        package="yt-dlp",
        version_getter=lambda: installed_version("yt-dlp"),
        bounds_getter=lambda: dependent_version_bounds("spotdl", "yt-dlp"),
    ),
    UpdatePolicy(
        package="ytmusicapi",
        version_getter=lambda: installed_version("ytmusicapi"),
        bounds_getter=lambda: dependent_version_bounds("spotdl", "ytmusicapi"),
    ),
    UpdatePolicy(
        package="spotdl",
        version_getter=lambda: installed_version("spotdl"),
        # No dependent bound exists for spotdl itself — self-limit to its
        # current major version instead (see the module comment above).
        bounds_getter=lambda: (None, same_major_ceiling(installed_version("spotdl") or "0")),
    ),
]


class UpdateChecker(QThread):
    """
    Background, once-a-day-per-package check against PyPI. Installs in-place
    via pip if a newer version is available and still within the policy's
    bound. Silent on any failure (offline, PyPI unreachable, package not
    installed, etc.) — this is best-effort maintenance, never something that
    should interrupt using the app.
    """

    def __init__(self, policy: UpdatePolicy, force: bool = False) -> None:
        super().__init__()
        self._p = policy
        self._force = force

    def run(self) -> None:
        p = self._p
        settings = QSettings("RippedRipper", "RipperGUI")
        settings_key = f"update_check_{p.package}"
        today = datetime.now(timezone.utc).date().isoformat()
        if not self._force and settings.value(settings_key) == today:
            return  # already checked today

        installed_str = p.version_getter()
        if not installed_str:
            return  # not installed in this environment; nothing to update

        try:
            req = urllib.request.Request(
                f"https://pypi.org/pypi/{p.package}/json", headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                latest_str = json.loads(resp.read())["info"]["version"]
        except Exception as exc:
            log(f"[UPDATE] Couldn't check for {p.package} updates: {exc}")
            return

        settings.setValue(settings_key, today)

        installed = version_tuple(installed_str)
        latest    = version_tuple(latest_str)
        if latest <= installed:
            log(f"[UPDATE] {p.package} {installed_str} is current.")
            return

        lo, hi = p.bounds_getter()
        if hi is not None and latest >= hi:
            log(f"[UPDATE] {p.package} {latest_str} is available but exceeds the allowed "
                f"version (<{'.'.join(map(str, hi))}) — skipping. Update it manually if you want it.")
            return

        log(f"[UPDATE] {p.package} {installed_str} -> {latest_str} available, updating...")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade",
                 "--disable-pip-version-check", f"{p.package}=={latest_str}"],
                capture_output=True, text=True, timeout=90,
            )
        except Exception as exc:
            log(f"[UPDATE] {p.package} update failed to run: {exc}")
            return

        if result.returncode == 0:
            log(f"[UPDATE] {p.package} updated to {latest_str}. "
                f"Restart Ripped Ripper to use it.")
        else:
            detail = (result.stderr or result.stdout or "").strip().splitlines()
            detail = detail[-1] if detail else "unknown error"
            log(f"[UPDATE] {p.package} update failed: {detail}")


# ─── Theming ─────────────────────────────────────────────────────────────────
#
# Everything visually customizable — accent color and text size — is driven
# from two values through this one template, rather than scattered hardcoded
# hex/px literals. Uses string.Template ($token) rather than str.format/f-string
# because the stylesheet is full of literal { } (every QSS rule block), which
# .format() would otherwise require escaping throughout.
#
# Status colors (success green, warning amber, error red) and the dark
# background/surface palette are intentionally NOT derived from the accent —
# they're semantic or structural, and letting an arbitrary accent choice repaint
# them risks illegible combinations. Only the accent-family swatches below (the
# ones that were already all one purple/indigo family) are derived from the
# single color the user picks.

DEFAULT_ACCENT    = "#8b5cf6"
DEFAULT_FONT_SCALE = 1.0   # 1.0 = the sizes the UI was designed at


def _hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in rgb)


def adjust_lightness(hex_color: str, factor: float) -> str:
    """factor > 1 lightens, < 1 darkens, applied on the HSL lightness channel."""
    r, g, b = _hex_to_rgb(hex_color)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = max(0.0, min(1.0, l * factor))
    return _rgb_to_hex(colorsys.hls_to_rgb(h, l, s))


def rotate_hue(hex_color: str, degrees: float) -> str:
    """Shift hue by `degrees`, keeping lightness/saturation — used to derive
    the gradient's second color from the single accent the user picks."""
    r, g, b = _hex_to_rgb(hex_color)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    h = (h + degrees / 360.0) % 1.0
    return _rgb_to_hex(colorsys.hls_to_rgb(h, l, s))


def is_valid_hex_color(value: str) -> bool:
    return bool(re.fullmatch(r"#[0-9a-fA-F]{6}", value or ""))


THEME_CACHE_DIR = Path(tempfile.gettempdir()) / "ripped_ripper_theme"


def triangle_arrow_path(hex_color: str, direction: str) -> str:
    """
    Writes a small solid-color triangle SVG to a cache file and returns its
    path, for QComboBox/QSpinBox arrow glyphs.

    Two things about Qt's QSS learned the hard way here: the usual CSS
    zero-size-element-plus-one-colored-border trick for drawing a triangle
    does NOT render correctly in Qt's style engine (it painted a filled
    square instead) — so an actual image is needed. And Qt's QSS `url()`
    only resolves real file paths / Qt resource paths, NOT `data:` URIs like
    browser CSS accepts — an inline data URI silently failed to render at
    all. Hence writing an actual file rather than embedding one inline.
    """
    points = "1,3 9,3 5,8" if direction == "down" else "1,7 9,7 5,2"
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
        f'<polygon points="{points}" fill="{hex_color}"/></svg>'
    )
    THEME_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"arrow_{direction}_{hex_color.lstrip('#')}.svg"
    path = THEME_CACHE_DIR / filename
    if not path.exists():
        path.write_text(svg)
    return path.as_posix()


STYLE_TEMPLATE = Template("""
* {
    font-family: -apple-system, 'SF Pro Display', 'Segoe UI', Arial, sans-serif;
    font-size: ${fs_base}px;
}

QMainWindow {
    background-color: #0a0a0f;
}

QWidget {
    background-color: transparent;
    color: #e2e8f0;
}

QWidget#root_bg {
    background-color: #0a0a0f;
}

QLabel#appTitle {
    color: $accent_light;
    letter-spacing: -0.5px;
    background: transparent;
}

/* ── Tabs ── */
QTabWidget::pane {
    border: 1px solid #1e1e2f;
    border-radius: 12px;
    background-color: #13131f;
    top: -1px;
}
QTabWidget {
    background: transparent;
}
QTabBar {
    background: transparent;
}
QTabBar::tab {
    background: #181825;
    color: #64748b;
    padding: 12px 32px;
    border: 1px solid #1e1e2f;
    border-bottom: none;
    border-radius: 10px 10px 0 0;
    margin-right: 6px;
    font-size: ${fs_md}px;
    font-weight: 600;
}
QTabBar::tab:selected {
    background: #13131f;
    color: $accent;
    border-color: #1e1e2f;
}
QTabBar::tab:hover:!selected {
    color: $accent_light;
    background: #1c1c2e;
}

/* ── Inputs ── */
QLineEdit {
    background-color: #1a1a2e;
    border: 1px solid #2d2d44;
    border-radius: 12px;
    padding: 12px 18px;
    color: #f8fafc;
    font-size: ${fs_base}px;
    selection-background-color: $accent_dark;
}
QLineEdit:focus {
    border-color: $accent;
    background-color: #1e1e36;
}
QLineEdit::placeholder {
    color: #475569;
}

/* ── Buttons ── */
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 $accent, stop:1 $accent2);
    color: white;
    border: none;
    border-radius: 12px;
    padding: 10px 24px;
    font-size: ${fs_md}px;
    font-weight: 700;
    letter-spacing: 0.5px;
}
QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 $accent_light, stop:1 $accent2_light);
}
QPushButton:pressed {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 $accent_dark, stop:1 $accent2_dark);
}
QPushButton:disabled {
    background: #1e1e2f;
    color: #475569;
}
QPushButton#ghost {
    background: transparent;
    border: 1px solid #2d2d44;
    color: $accent2_light;
}
QPushButton#ghost:hover {
    border-color: $accent;
    background: #1a1a2e;
    color: $accent_light;
}
QPushButton#ghost:disabled {
    background: transparent;
    border-color: #1e1e2f;
    color: #334155;
}

/* ── Cards ── */
QFrame#card {
    background-color: #1a1a2e;
    border: 1px solid #2d2d44;
    border-radius: 12px;
}
QFrame#card:hover {
    border-color: $accent2_dark;
    background-color: #1e1e36;
}

/* ── Scroll ── */
QScrollArea {
    border: none;
    background: transparent;
}
QScrollBar:vertical {
    background: transparent;
    width: 6px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #334155;
    border-radius: 3px;
    min-height: 24px;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: none;
    height: 0;
}

/* ── Progress ── */
QProgressBar {
    border: none;
    border-radius: 4px;
    background-color: #1a1a2e;
    max-height: 6px;
    text-align: center;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $accent, stop:1 $accent2);
    border-radius: 4px;
}
QLabel#progressLabel {
    color: $accent_light;
    font-size: ${fs_base}px;
    font-weight: 700;
}
QLabel#accentText {
    color: $accent_light;
    font-size: ${fs_sm}px;
    background: transparent;
}

/* ── Checkboxes ── */
QCheckBox {
    color: #94a3b8;
    spacing: 10px;
    font-size: ${fs_md}px;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 6px;
    border: 1px solid #334155;
    background: #1a1a2e;
}
QCheckBox::indicator:checked {
    background: $accent;
    border-color: $accent;
    image: none;
}
QCheckBox::indicator:disabled {
    background: #1e1e2f;
    border-color: #1e1e2f;
}

/* ── Combo box ── */
QComboBox {
    background-color: #1a1a2e;
    border: 1px solid #2d2d44;
    border-radius: 10px;
    padding: 6px 12px;
    color: #dde1f0;
    font-size: ${fs_sm}px;
    font-weight: 700;
    min-width: 76px;
    /* Without this, Fusion draws a dotted keyboard-focus rectangle inside
       the closed box — the "odd artifact" visible before you interact with it. */
    outline: none;
}
QComboBox:hover {
    border-color: $accent;
    background-color: #1e1e36;
}
QComboBox::drop-down {
    border: none;
    width: 22px;
}
QComboBox::down-arrow {
    image: url($down_arrow_uri);
    width: 10px;
    height: 10px;
    margin-right: 10px;
}
QComboBox QAbstractItemView {
    background-color: #1a1a2e;
    border: 1px solid #2d2d44;
    border-radius: 10px;
    color: #dde1f0;
    padding: 4px;
    outline: none;
    selection-background-color: $accent_dark;
    selection-color: #ffffff;
}

/* ── Sliders (Settings tab) ── */
QSlider::groove:horizontal {
    height: 4px;
    background: #2d2d44;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
    background: $accent;
}
QSlider::sub-page:horizontal {
    background: $accent;
    border-radius: 2px;
}

/* ── Spin boxes (Settings tab) ── */
QSpinBox {
    background-color: #1a1a2e;
    border: 1px solid #2d2d44;
    border-radius: 10px;
    /* Right padding clears room for the up/down buttons below so the number
       doesn't sit underneath them. */
    padding: 6px 26px 6px 10px;
    color: #dde1f0;
    font-size: ${fs_sm}px;
}
QSpinBox:hover {
    border-color: $accent;
}
/* Styling the box at all suppresses Qt's native-drawn spin buttons, so they
   have to be redrawn explicitly here or the box is left with no visible
   up/down control at all. */
QSpinBox::up-button, QSpinBox::down-button {
    width: 18px;
    border: none;
    background: #232338;
}
QSpinBox::up-button {
    subcontrol-origin: border;
    subcontrol-position: top right;
    border-top-right-radius: 10px;
    margin: 1px 1px 0 0;
}
QSpinBox::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    border-bottom-right-radius: 10px;
    margin: 0 1px 1px 0;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background: #2d2d44;
}
QSpinBox::up-arrow {
    image: url($up_arrow_uri);
    width: 8px;
    height: 8px;
}
QSpinBox::down-arrow {
    image: url($down_arrow_uri);
    width: 8px;
    height: 8px;
}
QSpinBox::up-arrow:disabled, QSpinBox::up-arrow:off {
    image: url($disabled_up_arrow_uri);
}
QSpinBox::down-arrow:disabled, QSpinBox::down-arrow:off {
    image: url($disabled_down_arrow_uri);
}

/* ── Console ── */
QTextEdit#console {
    background-color: #05050a;
    color: #10b981;
    font-family: "Menlo", "Consolas", monospace;
    font-size: ${fs_sm}px;
    border: 1px solid #1e1e2f;
    border-radius: 8px;
    padding: 10px;
}
""")


def build_stylesheet(accent: str, font_scale: float) -> str:
    if not is_valid_hex_color(accent):
        accent = DEFAULT_ACCENT
    font_scale = max(0.8, min(1.4, font_scale))
    arrow_color = adjust_lightness(rotate_hue(accent, -20), 1.22)  # == accent2_light

    return STYLE_TEMPLATE.substitute(
        accent=accent,
        accent_light=adjust_lightness(accent, 1.22),
        accent_dark=adjust_lightness(accent, 0.82),
        accent2=rotate_hue(accent, -20),
        accent2_light=arrow_color,
        accent2_dark=adjust_lightness(rotate_hue(accent, -20), 0.82),
        fs_base=round(14 * font_scale),
        fs_md=round(13 * font_scale),
        fs_sm=round(12 * font_scale),
        down_arrow_uri=triangle_arrow_path(arrow_color, "down"),
        up_arrow_uri=triangle_arrow_path(arrow_color, "up"),
        disabled_down_arrow_uri=triangle_arrow_path("#334155", "down"),
        disabled_up_arrow_uri=triangle_arrow_path("#334155", "up"),
    )


class AppearanceSettings(QObject):
    """
    App-wide accent color + text size, persisted via QSettings. Both Settings-
    tab controls and anything else wanting to react to a live theme change
    (there's currently just the one Settings tab, but this mirrors the
    FormatSetting pattern used for output format) listen on `changed`.
    """
    changed = pyqtSignal(str, float)   # (accent_hex, font_scale)

    def __init__(self) -> None:
        super().__init__()
        settings = QSettings("RippedRipper", "RipperGUI")
        accent = settings.value("accent_color", DEFAULT_ACCENT)
        self._accent = accent if is_valid_hex_color(accent) else DEFAULT_ACCENT
        try:
            self._font_scale = float(settings.value("font_scale", DEFAULT_FONT_SCALE))
        except (TypeError, ValueError):
            self._font_scale = DEFAULT_FONT_SCALE

    def accent(self) -> str:
        return self._accent

    def font_scale(self) -> float:
        return self._font_scale

    def apply(self, accent: str | None = None, font_scale: float | None = None) -> None:
        if accent is not None and is_valid_hex_color(accent):
            self._accent = accent
        if font_scale is not None:
            self._font_scale = max(0.8, min(1.4, font_scale))

        settings = QSettings("RippedRipper", "RipperGUI")
        settings.setValue("accent_color", self._accent)
        settings.setValue("font_scale", self._font_scale)

        stylesheet = build_stylesheet(self._accent, self._font_scale)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(stylesheet)
        self.changed.emit(self._accent, self._font_scale)

    def reset(self) -> None:
        self.apply(accent=DEFAULT_ACCENT, font_scale=DEFAULT_FONT_SCALE)


appearance_settings = AppearanceSettings()


# ─── Utility ─────────────────────────────────────────────────────────────────

def sanitize(name: str) -> str:
    """Strip characters that are illegal in filenames."""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip()


def grow_with_content(widget: QWidget, min_height: int) -> None:
    """
    Set a floor height a widget won't shrink below, while still letting it
    grow taller when its content needs more room (e.g. the text-size setting
    scaled up). QPushButton/QLineEdit default to a Fixed vertical size
    policy, under which a plain setMinimumHeight() alone still caps the
    widget at exactly that floor instead of letting it grow to fit — this
    also switches the vertical policy to Minimum, which is what actually
    allows the growth.
    """
    widget.setMinimumHeight(min_height)
    policy = widget.sizePolicy()
    policy.setVerticalPolicy(QSizePolicy.Policy.Minimum)
    widget.setSizePolicy(policy)


_ytmusic_client: YTMusic | None = None
_ytmusic_lock = threading.Lock()

def ytmusic() -> YTMusic:
    """
    Shared YTMusic client. Constructing one per track costs a fresh setup and
    connection each time, which adds up across a large playlist.
    """
    global _ytmusic_client
    with _ytmusic_lock:
        if _ytmusic_client is None:
            _ytmusic_client = YTMusic()
        return _ytmusic_client

# ─── Logger ──────────────────────────────────────────────────────────────────

class AppLogger(QObject):
    log_msg = pyqtSignal(str)

app_logger = AppLogger()
_log_lock = threading.Lock()

def log(msg: str):
    """Emit a timestamped log message to the console UI and stdout."""
    stamped = f"[{datetime.now():%H:%M:%S}] {msg}"
    app_logger.log_msg.emit(stamped)
    # Lock around the write: print() isn't atomic, so with several rips running
    # at once the worker threads otherwise interleave mid-line. Flush so output
    # appears live instead of sitting in a buffer when stdout is redirected to
    # a file (as the .app launcher does).
    with _log_lock:
        print(stamped, flush=True)


def human_size(num_bytes: float) -> str:
    """Format a byte count as a compact human-readable string."""
    if not num_bytes:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


class YtdlpLogger:
    """
    Routes yt-dlp's internal output through the app logger so it lands in the
    GUI console (and the launcher log) instead of being written straight to
    stdout, where its carriage-return progress lines mangle everything else.
    """

    def __init__(self, tag: str) -> None:
        self._tag = tag

    def debug(self, msg: str) -> None:
        pass  # far too noisy to surface; progress is reported via the hook

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        log(f"{self._tag} warning: {msg.strip()}")

    def error(self, msg: str) -> None:
        log(f"{self._tag} yt-dlp error: {msg.strip()}")


def build_ydl_opts(tag: str, out_template: str, audio_format: str) -> dict:
    """
    Shared yt-dlp config for both rip paths: grab the best audio stream and
    hand it to ffmpeg to produce the requested format.
    """
    spec = AUDIO_FORMATS.get(audio_format, AUDIO_FORMATS[DEFAULT_AUDIO_FORMAT])
    progress_state = {"last_pct": 0}

    def progress_hook(d: dict) -> None:
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done  = d.get("downloaded_bytes") or 0
            if not total:
                return
            pct = int(done * 100 / total)
            # report roughly every 25% instead of on every chunk
            if pct >= progress_state["last_pct"] + 25:
                progress_state["last_pct"] = pct
                speed = d.get("speed") or 0
                log(f"{tag} downloading {pct}% of {human_size(total)} "
                    f"at {human_size(speed)}/s")
        elif status == "finished":
            log(f"{tag} download finished, converting to {audio_format}...")

    # For m4a, ask for YouTube's native AAC stream so ffmpeg can copy it
    # straight through instead of re-encoding. Other formats re-encode anyway,
    # so just take the best audio available.
    fmt_selector = (
        "bestaudio[ext=m4a]/bestaudio/best" if audio_format == "m4a"
        else "bestaudio/best"
    )

    opts = {
        "format": fmt_selector,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": spec["codec"],
            "preferredquality": spec["quality"],
        }],
        "outtmpl": out_template,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,          # suppress yt-dlp's own stdout progress bar
        "concurrent_fragment_downloads": 4,
        # Running several rips at once makes YouTube more likely to answer with
        # HTTP 429. Retry with backoff and space out extraction requests a
        # little so a throttled track recovers instead of failing outright.
        "retries": 5,
        "extractor_retries": 3,
        "fragment_retries": 5,
        "sleep_interval_requests": 0.5,
        "logger": YtdlpLogger(tag),
        "progress_hooks": [progress_hook],
    }

    if spec.get("pp_args"):
        opts["postprocessor_args"] = {"extractaudio": spec["pp_args"]}

    return opts


# Errors that will never succeed on a retry — the track simply isn't available
# to us, so retrying just burns time on every dead track in a playlist.
PERMANENT_ERRORS = (
    "video unavailable",
    "private video",
    "has been removed",
    "removed by the uploader",
    "members-only",
    "confirm your age",
    "not available in your country",
    "does not exist",
    "this live event has ended",
)


def is_permanent_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in PERMANENT_ERRORS)


def download_track(
    tag: str,
    url: str,
    out_template: str,
    audio_format: str,
    attempts: int = 3,
) -> None:
    """
    Download one track, retrying transient YouTube throttling (HTTP 403/429),
    which gets more likely with several rips running at once.

    Each retry builds a fresh YoutubeDL and re-runs extraction: a 403 usually
    means the stream URL we were handed has expired or been rejected, so
    retrying the *same* URL is useless — we need newly extracted ones.
    Permanently unavailable tracks fail immediately instead of retrying.
    """
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            opts = build_ydl_opts(tag, out_template, audio_format)
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            return
        except Exception as exc:
            last_error = exc
            if is_permanent_error(exc):
                raise
            if attempt < attempts:
                delay = 2 * attempt      # 2s, then 4s
                log(f"{tag} attempt {attempt}/{attempts} failed, retrying in {delay}s...")
                time.sleep(delay)
    raise last_error  # type: ignore[misc]


def existing_rip(output_dir: Path, stem: str, audio_format: str) -> Path | None:
    """
    Return an already-downloaded file for this track in the requested format.

    Only an exact-format match counts as "already ripped": if you deliberately
    switch to WAV, having the track as an MP3 shouldn't stop the WAV rip.
    """
    candidate = output_dir / f"{stem}.{audio_format}"
    return candidate if candidate.exists() else None


def other_format_rips(output_dir: Path, stem: str, audio_format: str) -> list[Path]:
    """Copies of this track in *other* formats, worth mentioning in the log."""
    return [
        p for ext in KNOWN_AUDIO_EXTS
        if ext != audio_format and (p := output_dir / f"{stem}.{ext}").exists()
    ]


# ─── Signals ─────────────────────────────────────────────────────────────────

class WorkerSignals(QObject):
    """Cross-thread signal bus for download workers."""
    started  = pyqtSignal(str)        # track_id
    finished = pyqtSignal(str)        # track_id
    failed   = pyqtSignal(str, str)   # track_id, error_message
    skipped  = pyqtSignal(str)        # track_id (file already exists)


# ─── Background Workers ───────────────────────────────────────────────────────

class SearchWorker(QThread):
    """Queries YouTube Music on a background thread."""
    results_ready = pyqtSignal(list)
    error         = pyqtSignal(str)

    def __init__(self, query: str) -> None:
        super().__init__()
        self.query = query

    def run(self) -> None:
        try:
            log(f"[SEARCH] Querying YouTube Music for '{self.query}'...")
            started = time.monotonic()
            yt = ytmusic()
            results = yt.search(self.query, filter="songs", limit=8)
            if not results:
                log("[SEARCH] No song matches; retrying as an unfiltered search...")
                results = yt.search(self.query, limit=8)
            log(f"[SEARCH] Found {len(results)} results in {time.monotonic() - started:.1f}s")
            self.results_ready.emit(results[:8])
        except Exception as exc:
            log(f"[SEARCH] Failed: {exc}")
            self.error.emit(str(exc))


class DownloadWorker(QRunnable):
    """Downloads a single song by YouTube Music video ID via yt-dlp."""

    def __init__(
        self,
        video_id:     str,
        title:        str,
        artist:       str,
        output_dir:   Path,
        signals:      WorkerSignals,
        audio_format: str = DEFAULT_AUDIO_FORMAT,
    ) -> None:
        super().__init__()
        self.video_id     = video_id
        self.title        = title
        self.artist       = artist
        self.output_dir   = output_dir
        self.signals      = signals
        self.audio_format = audio_format

    def run(self) -> None:
        safe_title  = sanitize(self.title)
        safe_artist = sanitize(self.artist)
        stem        = f"{safe_artist} - {safe_title}"
        filename    = f"{stem}.{self.audio_format}"
        target      = self.output_dir / filename
        tag         = f"[RIP] {stem}:"

        already = existing_rip(self.output_dir, stem, self.audio_format)
        if already:
            log(f"{tag} skipped, already have {already.name}")
            self.signals.skipped.emit(self.video_id)
            return

        others = other_format_rips(self.output_dir, stem, self.audio_format)
        if others:
            log(f"{tag} have {others[0].name}, re-ripping as {self.audio_format}")

        log(f"{tag} starting (video ID {self.video_id}) -> {self.output_dir}")
        self.signals.started.emit(self.video_id)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        url = f"https://music.youtube.com/watch?v={self.video_id}"

        started = time.monotonic()
        try:
            download_track(
                tag, url, str(self.output_dir / f"{stem}.%(ext)s"), self.audio_format
            )
            size = human_size(target.stat().st_size) if target.exists() else "?"
            log(f"{tag} done in {time.monotonic() - started:.1f}s ({size}) -> {filename}")
            self.signals.finished.emit(self.video_id)
        except Exception as exc:
            log(f"{tag} FAILED after {time.monotonic() - started:.1f}s - {exc}")
            self.signals.failed.emit(self.video_id, str(exc))


@dataclass
class SimpleSong:
    """
    Minimal stand-in for spotdl's Song type, used for Apple Music tracks.
    PlaylistTrackDownloader and TrackRow only ever read `.name` and
    `.artists`, so this is all that's needed to reuse that pipeline.
    """
    name: str
    artists: list = field(default_factory=list)


class PlaylistFetcher(QThread):
    """
    Fetches a playlist's track list from Spotify (via spotdl) or Apple Music
    (by parsing its public playlist page), depending on the URL.
    """
    tracks_ready   = pyqtSignal(str, list)   # (playlist_name, [Song, ...])
    status_update  = pyqtSignal(str)
    error          = pyqtSignal(str)

    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url

    def run(self) -> None:
        try:
            if "music.apple.com" in self.url:
                self._fetch_apple_music()
            elif "spotify.com" in self.url:
                self._fetch_spotify()
            else:
                self.error.emit(
                    "Please paste a Spotify or Apple Music playlist URL."
                )
        except Exception as exc:
            log(f"[PLAYLIST] Fatal Error during fetch: {exc}")
            self.error.emit(str(exc))

    # ── Spotify ──────────────────────────────────────────────────────────────

    def _fetch_spotify(self) -> None:
        log(f"[PLAYLIST] Fetching Spotify playlist info for: {self.url}...")
        # ── 1. Resolve playlist name (no auth required) ──────────────────
        playlist_name = "Spotify Playlist"
        try:
            req = urllib.request.Request(
                f"https://open.spotify.com/oembed?url={self.url}",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                playlist_name = data.get("title", playlist_name)
        except Exception:
            pass  # name stays as default; non-fatal

        self.status_update.emit(f'Fetching tracks for "{playlist_name}" …')

        # ── 2. Fetch songs via spotdl ────────────────────────────────────
        try:
            from spotdl import Spotdl  # type: ignore
        except ImportError:
            log("[PLAYLIST] Error: spotdl is not installed.")
            self.error.emit(
                "spotdl is not installed.\n"
                "Run:  pip install spotdl   (or: pip install -r requirements_gui.txt)"
            )
            return

        log(f"[PLAYLIST] spotdl found. Extracting tracks (this may take a moment)...")

        # Hook into spotdl to log each track as it's parsed from the playlist.
        # This touches an undocumented internal method with no API stability
        # guarantee, so a spotdl update could rename or remove it at any time —
        # if that happens, skip the nice per-track logging rather than failing
        # the whole playlist fetch over what's just a progress cosmetic.
        hook_installed = False
        _original_from_missing = None
        try:
            from spotdl.types.song import Song as SpotdlSong  # type: ignore
            _original_from_missing = SpotdlSong.from_missing_data.__func__
            _track_counter = [0]

            @classmethod  # type: ignore
            def _hooked_from_missing(cls, **kwargs):
                song = _original_from_missing(cls, **kwargs)
                _track_counter[0] += 1
                artists = getattr(song, 'artists', None) or []
                artist_name = artists[0] if (artists and isinstance(artists[0], str)) else (getattr(song, 'artist', None) or "Unknown")
                log(f"[PLAYLIST] #{_track_counter[0]:>3d}  {artist_name} - {song.name}")
                return song

            SpotdlSong.from_missing_data = _hooked_from_missing
            hook_installed = True
        except Exception as exc:
            log(f"[PLAYLIST] Note: per-track progress logging unavailable ({exc}); continuing without it.")

        try:
            client = Spotdl(
                client_id=SPOTDL_CLIENT_ID,
                client_secret=SPOTDL_CLIENT_SECRET,
            )
            songs = client.search([self.url])
        finally:
            # Restore original method so repeated fetches don't stack hooks
            if hook_installed:
                SpotdlSong.from_missing_data = classmethod(_original_from_missing)

        log(f"[PLAYLIST] Successfully extracted {len(songs)} tracks from playlist '{playlist_name}'.")
        self.tracks_ready.emit(playlist_name, songs)

    # ── Apple Music ──────────────────────────────────────────────────────────

    def _fetch_apple_music(self) -> None:
        log(f"[PLAYLIST] Fetching Apple Music playlist info for: {self.url}...")

        req = urllib.request.Request(self.url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # Apple Music's web app embeds the fully-resolved page state (including
        # the track list) as JSON in a server-rendered <script> tag — no API
        # key or auth needed, same spirit as the Spotify oembed lookup above.
        match = re.search(
            r'<script type="application/json" id="serialized-server-data">(.*?)</script>',
            html,
            re.S,
        )
        if not match:
            self.error.emit(
                "Could not read this Apple Music playlist page "
                "(the page format may have changed)."
            )
            return

        try:
            payload = json.loads(match.group(1))
            sections = payload["data"][0]["data"]["sections"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            self.error.emit(f"Could not parse Apple Music playlist data: {exc}")
            return

        header = next(
            (s for s in sections if s.get("itemKind") == "containerDetailHeaderLockup"),
            None,
        )
        playlist_name = "Apple Music Playlist"
        if header and header.get("items"):
            playlist_name = header["items"][0].get("title", playlist_name)

        track_section = next(
            (s for s in sections if s.get("itemKind") == "trackLockup"), None
        )
        if not track_section or not track_section.get("items"):
            self.error.emit("No tracks found on this Apple Music playlist page.")
            return

        self.status_update.emit(f'Fetching tracks for "{playlist_name}" …')

        songs = []
        for i, item in enumerate(track_section["items"], start=1):
            title = item.get("title")
            if not title:
                continue
            subtitle_links = item.get("subtitleLinks") or []
            artist = subtitle_links[0]["title"] if subtitle_links else "Unknown Artist"
            songs.append(SimpleSong(name=title, artists=[artist]))
            log(f"[PLAYLIST] #{i:>3d}  {artist} - {title}")

        log(f"[PLAYLIST] Successfully extracted {len(songs)} tracks from playlist '{playlist_name}'.")
        self.tracks_ready.emit(playlist_name, songs)


class PlaylistTrackDownloader(QRunnable):
    """
    Downloads one playlist track (from Spotify or Apple Music) by matching
    it on YouTube Music and ripping via yt-dlp — same pipeline as the search tab.
    """

    def __init__(
        self,
        song:       object,           # spotdl Song
        output_dir: Path,
        signals:      WorkerSignals,
        track_id:     str,
        audio_format: str = DEFAULT_AUDIO_FORMAT,
    ) -> None:
        super().__init__()
        self.song         = song
        self.output_dir   = output_dir
        self.signals      = signals
        self.track_id     = track_id
        self.audio_format = audio_format

    def run(self) -> None:
        tag = "[RIP]"
        started = time.monotonic()
        try:
            title   = self.song.name
            artists = self.song.artists or ["Unknown"]
            # artists can be List[str] (spotdl 4.x)
            artist  = artists[0] if isinstance(artists[0], str) else str(artists[0])

            safe_title  = sanitize(title)
            safe_artist = sanitize(artist)
            stem        = f"{safe_artist} - {safe_title}"
            filename    = f"{stem}.{self.audio_format}"
            target      = self.output_dir / filename
            tag         = f"[RIP] {stem}:"

            already = existing_rip(self.output_dir, stem, self.audio_format)
            if already:
                log(f"{tag} skipped, already have {already.name}")
                self.signals.skipped.emit(self.track_id)
                return

            self.signals.started.emit(self.track_id)
            self.output_dir.mkdir(parents=True, exist_ok=True)

            log(f"{tag} matching on YouTube Music...")
            yt      = ytmusic()
            query   = f"{artist} {title}"
            results = yt.search(query, filter="songs", limit=1)
            if not results:
                results = yt.search(query, limit=1)

            if not results:
                log(f"{tag} FAILED - no match on YouTube Music")
                self.signals.failed.emit(self.track_id, "Not found on YouTube Music")
                return

            video_id = results[0].get("videoId")
            if not video_id:
                log(f"{tag} FAILED - match had no video ID")
                self.signals.failed.emit(self.track_id, "No video ID found")
                return

            log(f"{tag} matched video ID {video_id} -> {self.output_dir}")
            url = f"https://music.youtube.com/watch?v={video_id}"

            download_track(
                tag, url, str(self.output_dir / f"{stem}.%(ext)s"), self.audio_format
            )

            size = human_size(target.stat().st_size) if target.exists() else "?"
            log(f"{tag} done in {time.monotonic() - started:.1f}s ({size}) -> {filename}")
            self.signals.finished.emit(self.track_id)

        except Exception as exc:
            log(f"{tag} FAILED after {time.monotonic() - started:.1f}s - {exc}")
            self.signals.failed.emit(self.track_id, str(exc))


# ─── Reusable Widgets ─────────────────────────────────────────────────────────

class ResultCard(QFrame):
    """Card displaying one search result with a Rip button."""

    download_requested = pyqtSignal(dict)

    _STATUS = {
        "downloading": ("Ripping...", "#f59e0b", False),
        "done":        ("Done",      "#10b981", False),
        "skipped":     ("Exists",    "#6366f1", False),
        "failed":      ("Failed",    "#ef4444", True),
    }

    def __init__(self, result: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.result = result
        self.setObjectName("card")
        grow_with_content(self, 72)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 10, 14, 10)
        layout.setSpacing(14)

        # ── Track metadata ──────────────────────────────────────────────────
        title   = result.get("title", "Unknown Title")
        artists = result.get("artists") or []
        artist  = ", ".join(a.get("name", "") for a in artists) or "Unknown Artist"
        album   = (result.get("album") or {}).get("name", "")
        dur     = result.get("duration", "")
        meta    = artist
        if album:
            meta += f"  ·  {album}"
        if dur:
            meta += f"  ·  {dur}"

        info = QVBoxLayout()
        info.setSpacing(3)

        title_lbl = QLabel(title)
        title_lbl.setFont(QFont("", 13, QFont.Weight.DemiBold))
        title_lbl.setStyleSheet("color: #dde1f0; background: transparent;")

        meta_lbl = QLabel(meta)
        meta_lbl.setStyleSheet("color: #55557a; font-size: 12px; background: transparent;")

        info.addWidget(title_lbl)
        info.addWidget(meta_lbl)

        # ── Status label ────────────────────────────────────────────────────
        self._status_lbl = QLabel("")
        self._status_lbl.setMinimumWidth(88)
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_lbl.setStyleSheet("font-size: 12px; font-weight: 700; background: transparent;")

        # ── Rip button ──────────────────────────────────────────────────────
        self._rip_btn = QPushButton("Rip")
        self._rip_btn.setMinimumSize(100, 38)
        self._rip_btn.clicked.connect(lambda: self.download_requested.emit(self.result))

        layout.addLayout(info, stretch=1)
        layout.addWidget(self._status_lbl)
        layout.addWidget(self._rip_btn)

    def set_status(self, status: str) -> None:
        label, color, re_enable = self._STATUS.get(status, ("", "#dde1f0", True))
        self._status_lbl.setText(label)
        self._status_lbl.setStyleSheet(
            f"color: {color}; font-size: 12px; font-weight: 700; background: transparent;"
        )
        self._rip_btn.setEnabled(re_enable)
        if status == "downloading":
            self._rip_btn.setText("...")
        elif status in ("done", "skipped"):
            self._rip_btn.setText("OK")
        elif status == "failed":
            self._rip_btn.setText("Retry")


class TrackRow(QWidget):
    """Single row in the playlist track list."""

    _ICONS = {
        "waiting":     ("·",   "#44446a"),
        "downloading": ("...", "#f59e0b"),
        "done":        ("OK",  "#10b981"),
        "skipped":     ("-",   "#6366f1"),
        "failed":      ("Err", "#ef4444"),
    }

    def __init__(
        self,
        song:     object,
        track_id: str,
        parent:   QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.track_id = track_id
        self.song     = song

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 5, 14, 5)
        layout.setSpacing(12)

        self.checkbox = QCheckBox()
        self.checkbox.setChecked(True)

        title   = song.name
        artists = song.artists or ["Unknown"]
        artist  = artists[0] if isinstance(artists[0], str) else str(artists[0])

        info = QVBoxLayout()
        info.setSpacing(2)

        title_lbl = QLabel(title)
        title_lbl.setFont(QFont("", 13))
        title_lbl.setStyleSheet("color: #dde1f0; background: transparent;")

        artist_lbl = QLabel(str(artist))
        artist_lbl.setStyleSheet("color: #55557a; font-size: 12px; background: transparent;")

        info.addWidget(title_lbl)
        info.addWidget(artist_lbl)

        self._icon_lbl = QLabel("·")
        self._icon_lbl.setMinimumWidth(22)
        self._icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_lbl.setStyleSheet("color: #44446a; font-size: 16px; font-weight: bold; background: transparent;")

        layout.addWidget(self.checkbox)
        layout.addLayout(info, stretch=1)
        layout.addWidget(self._icon_lbl)

    def set_status(self, status: str) -> None:
        icon, color = self._ICONS.get(status, ("·", "#44446a"))
        self._icon_lbl.setText(icon)
        self._icon_lbl.setStyleSheet(
            f"color: {color}; font-size: 16px; font-weight: bold; background: transparent;"
        )
        if status != "waiting":
            self.checkbox.setEnabled(False)

    def is_selected(self) -> bool:
        return self.checkbox.isChecked()


class FormatSetting(QObject):
    """
    App-wide "what format do we rip to" setting. Both tabs show a picker, and
    this keeps them in sync (and persisted) rather than letting each tab drift.
    """
    changed = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self._settings = QSettings("RippedRipper", "RipperGUI")
        stored = self._settings.value("audio_format", DEFAULT_AUDIO_FORMAT)
        self._value = stored if stored in AUDIO_FORMATS else DEFAULT_AUDIO_FORMAT

    def value(self) -> str:
        return self._value

    def set_value(self, fmt: str) -> None:
        if fmt not in AUDIO_FORMATS or fmt == self._value:
            return
        self._value = fmt
        self._settings.setValue("audio_format", fmt)
        log(f"[SETTINGS] Output format set to {fmt}")
        self.changed.emit(fmt)


audio_format_setting = FormatSetting()


class OutputFolderRow(QWidget):
    """
    'Save to: <path>  [Choose Folder…]   Format: [ ▾ ]' row.
    The native folder picker lets the user create a new folder in place,
    so this covers both "pick a location" and "make a new folder" in one dialog.
    """

    changed = pyqtSignal(Path)

    def __init__(self, initial: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dir = initial

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        tag = QLabel("Save to:")
        tag.setStyleSheet("color: #64748b; font-size: 12px; font-weight: 700; background: transparent;")

        self._path_lbl = QLabel(str(self._dir))
        self._path_lbl.setObjectName("accentText")
        self._path_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        choose_btn = QPushButton("Choose Folder…")
        choose_btn.setObjectName("ghost")
        grow_with_content(choose_btn, 38)
        choose_btn.clicked.connect(self._choose)

        fmt_tag = QLabel("Format:")
        fmt_tag.setStyleSheet("color: #64748b; font-size: 12px; font-weight: 700; background: transparent;")

        self._fmt_combo = QComboBox()
        grow_with_content(self._fmt_combo, 38)
        self._fmt_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        for key, spec in AUDIO_FORMATS.items():
            self._fmt_combo.addItem(spec["label"], key)
            self._fmt_combo.setItemData(
                self._fmt_combo.count() - 1, spec["hint"], Qt.ItemDataRole.ToolTipRole
            )
        self._fmt_combo.setCurrentIndex(
            self._fmt_combo.findData(audio_format_setting.value())
        )
        self._fmt_combo.currentIndexChanged.connect(self._on_format_picked)
        # Follow changes made from the other tab's picker
        audio_format_setting.changed.connect(self._sync_format)

        layout.addWidget(tag)
        layout.addWidget(self._path_lbl, stretch=1)
        layout.addWidget(choose_btn)
        layout.addWidget(fmt_tag)
        layout.addWidget(self._fmt_combo)

    def _choose(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self,
            "Choose (or create) a folder to save rips to",
            str(self._dir),
            QFileDialog.Option.ShowDirsOnly,
        )
        if chosen:
            self._dir = Path(chosen)
            self._path_lbl.setText(str(self._dir))
            self.changed.emit(self._dir)

    def _on_format_picked(self, _index: int) -> None:
        audio_format_setting.set_value(self._fmt_combo.currentData())

    def _sync_format(self, fmt: str) -> None:
        idx = self._fmt_combo.findData(fmt)
        if idx >= 0 and idx != self._fmt_combo.currentIndex():
            self._fmt_combo.blockSignals(True)
            self._fmt_combo.setCurrentIndex(idx)
            self._fmt_combo.blockSignals(False)

    def path(self) -> Path:
        return self._dir


# ─── Tabs ─────────────────────────────────────────────────────────────────────

class SearchTab(QWidget):
    """Tab 1 — search YouTube Music and rip individual songs."""

    def __init__(self, pool: QThreadPool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pool          = pool
        self._cards: dict[str, ResultCard] = {}
        self._search_worker: SearchWorker | None = None
        # Keep signals alive (QRunnable doesn't retain them)
        self._signal_refs: list[WorkerSignals] = []

        self._settings = QSettings("RippedRipper", "RipperGUI")
        self._output_dir = Path(self._settings.value("search_output_dir", str(SEARCH_DIR)))

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 20)
        root.setSpacing(14)

        # ── Search row ──────────────────────────────────────────────────────
        row = QHBoxLayout()
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search for a song or artist …")
        grow_with_content(self._search_input, 48)
        self._search_input.returnPressed.connect(self._do_search)

        self._search_btn = QPushButton("Search")
        grow_with_content(self._search_btn, 48)
        self._search_btn.setMinimumWidth(110)
        self._search_btn.clicked.connect(self._do_search)

        row.addWidget(self._search_input, stretch=1)
        row.addWidget(self._search_btn)
        root.addLayout(row)

        # ── Output folder row ───────────────────────────────────────────────
        self._folder_row = OutputFolderRow(self._output_dir)
        self._folder_row.changed.connect(self._on_output_dir_changed)
        root.addWidget(self._folder_row)

        # ── Status ──────────────────────────────────────────────────────────
        self._status = QLabel("Search for any track to rip it in your chosen format")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet("color: #44446a; font-size: 13px;")
        root.addWidget(self._status)

        # ── Results scroll area ─────────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._results_container = QWidget()
        self._results_layout    = QVBoxLayout(self._results_container)
        self._results_layout.setContentsMargins(0, 0, 4, 0)
        self._results_layout.setSpacing(8)
        self._results_layout.addStretch()

        self._scroll.setWidget(self._results_container)
        root.addWidget(self._scroll, stretch=1)

        # ── Bottom button ───────────────────────────────────────────────────
        open_btn = QPushButton("Open Folder")
        open_btn.setObjectName("ghost")
        grow_with_content(open_btn, 40)
        open_btn.clicked.connect(self._open_folder)
        root.addWidget(open_btn)

    # ── Private helpers ─────────────────────────────────────────────────────

    def _on_output_dir_changed(self, new_dir: Path) -> None:
        self._output_dir = new_dir
        self._settings.setValue("search_output_dir", str(new_dir))

    def _do_search(self) -> None:
        query = self._search_input.text().strip()
        if not query:
            return
        self._search_btn.setEnabled(False)
        self._search_btn.setText("…")
        self._status.setText(f'Searching for "{query}" …')
        self._clear_results()

        self._search_worker = SearchWorker(query)
        self._search_worker.results_ready.connect(self._on_results)
        self._search_worker.error.connect(
            lambda e: self._status.setText(f"Error: {e}")
        )
        self._search_worker.finished.connect(self._on_search_finished)
        self._search_worker.start()

    def _on_search_finished(self) -> None:
        self._search_btn.setEnabled(True)
        self._search_btn.setText("Search")

    def _on_results(self, results: list) -> None:
        self._clear_results()
        if not results:
            self._status.setText("No results found — try a different search.")
            return

        self._status.setText(
            f"{len(results)} results found  ·  downloads -> {self._output_dir}/"
        )
        for result in results:
            vid = result.get("videoId")
            if not vid:
                continue
            card = ResultCard(result)
            card.download_requested.connect(self._on_download_card)
            self._cards[vid] = card
            self._results_layout.insertWidget(
                self._results_layout.count() - 1, card
            )

    def _clear_results(self) -> None:
        self._cards.clear()
        while self._results_layout.count() > 1:
            item = self._results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _on_download_card(self, result: dict) -> None:
        vid    = result.get("videoId", "")
        title  = result.get("title", "Unknown")
        artists = result.get("artists") or []
        artist = ", ".join(a.get("name", "") for a in artists) or "Unknown"

        card = self._cards.get(vid)
        if card:
            card.set_status("downloading")

        sigs = WorkerSignals()
        self._signal_refs.append(sigs)  # keep alive

        sigs.finished.connect(lambda tid: self._update_card(tid, "done"))
        sigs.skipped.connect(lambda tid:  self._update_card(tid, "skipped"))
        sigs.failed.connect(lambda tid, _: self._update_card(tid, "failed"))

        worker = DownloadWorker(
            vid, title, artist, self._output_dir, sigs, audio_format_setting.value()
        )
        self._pool.start(worker)

    def _update_card(self, track_id: str, status: str) -> None:
        card = self._cards.get(track_id)
        if card:
            card.set_status(status)

    def _open_folder(self) -> None:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._output_dir)))


class PlaylistTab(QWidget):
    """Tab 2 — paste a Spotify or Apple Music playlist URL, fetch tracks, download all."""

    def __init__(self, pool: QThreadPool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pool          = pool
        self._track_rows:   dict[str, TrackRow] = {}
        self._songs_map:    dict[str, object]   = {}
        self._signal_refs:  list[WorkerSignals] = []
        self._fetcher:      PlaylistFetcher | None = None
        self._playlist_name = ""
        self._total         = 0
        self._completed     = 0
        self._tally         = {"done": 0, "skipped": 0, "failed": 0}
        self._batch_started = 0.0

        self._settings = QSettings("RippedRipper", "RipperGUI")
        self._output_dir = Path(self._settings.value("playlist_output_dir", str(PLAYLIST_DIR)))

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 20)
        root.setSpacing(14)

        # ── URL row ─────────────────────────────────────────────────────────
        row = QHBoxLayout()
        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText(
            "Paste a Spotify or Apple Music playlist URL …"
        )
        grow_with_content(self._url_input, 48)
        self._url_input.returnPressed.connect(self._fetch_playlist)

        self._fetch_btn = QPushButton("Fetch")
        grow_with_content(self._fetch_btn, 48)
        self._fetch_btn.setMinimumWidth(110)
        self._fetch_btn.clicked.connect(self._fetch_playlist)

        row.addWidget(self._url_input, stretch=1)
        row.addWidget(self._fetch_btn)
        root.addLayout(row)

        # ── Output folder row ───────────────────────────────────────────────
        self._folder_row = OutputFolderRow(self._output_dir)
        self._folder_row.changed.connect(self._on_output_dir_changed)
        root.addWidget(self._folder_row)

        # ── Status ──────────────────────────────────────────────────────────
        self._status = QLabel("Paste a Spotify or Apple Music playlist link to fetch and batch-download all tracks")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet("color: #44446a; font-size: 13px;")
        root.addWidget(self._status)

        # ── Track list scroll ────────────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._tracks_container = QWidget()
        self._tracks_layout    = QVBoxLayout(self._tracks_container)
        self._tracks_layout.setContentsMargins(0, 0, 4, 0)
        self._tracks_layout.setSpacing(2)
        self._tracks_layout.addStretch()

        self._scroll.setWidget(self._tracks_container)
        root.addWidget(self._scroll, stretch=1)

        # ── Progress ─────────────────────────────────────────────────────────
        self._progress_bar = QProgressBar()
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedHeight(5)
        self._progress_bar.hide()

        self._progress_lbl = QLabel("")
        self._progress_lbl.setObjectName("progressLabel")
        self._progress_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        root.addWidget(self._progress_bar)
        root.addWidget(self._progress_lbl)

        # ── Bottom row ───────────────────────────────────────────────────────
        bottom = QHBoxLayout()
        self._download_btn = QPushButton("Download Selected")
        grow_with_content(self._download_btn, 44)
        self._download_btn.setEnabled(False)
        self._download_btn.clicked.connect(self._start_downloads)

        self._open_btn = QPushButton("Open Folder")
        self._open_btn.setObjectName("ghost")
        grow_with_content(self._open_btn, 44)
        self._open_btn.setMinimumWidth(145)
        self._open_btn.setEnabled(False)
        self._open_btn.clicked.connect(self._open_folder)

        bottom.addWidget(self._download_btn, stretch=1)
        bottom.addWidget(self._open_btn)
        root.addLayout(bottom)

    def _on_output_dir_changed(self, new_dir: Path) -> None:
        self._output_dir = new_dir
        self._settings.setValue("playlist_output_dir", str(new_dir))

    # ── Fetch ────────────────────────────────────────────────────────────────

    def _fetch_playlist(self) -> None:
        url = self._url_input.text().strip()
        if not url or not any(d in url for d in ("spotify.com", "music.apple.com")):
            self._status.setText("Please enter a valid Spotify or Apple Music playlist URL.")
            return

        self._fetch_btn.setEnabled(False)
        self._fetch_btn.setText("…")
        self._download_btn.setEnabled(False)
        self._status.setText("Connecting …")
        self._clear_tracks()
        self._progress_bar.hide()
        self._progress_lbl.setText("")

        self._fetcher = PlaylistFetcher(url)
        self._fetcher.tracks_ready.connect(self._on_tracks_ready)
        self._fetcher.status_update.connect(lambda m: self._status.setText(m))
        self._fetcher.error.connect(self._on_fetch_error)
        self._fetcher.finished.connect(self._on_fetch_finished)
        self._fetcher.start()

    def _on_tracks_ready(self, playlist_name: str, songs: list) -> None:
        self._playlist_name = playlist_name
        self._clear_tracks()

        if not songs:
            self._status.setText("No tracks found in this playlist.")
            return

        self._status.setText(
            f"{playlist_name}  ·  {len(songs)} tracks  "
            f"->  {self._output_dir}/{sanitize(playlist_name)}/"
        )

        for i, song in enumerate(songs):
            tid = f"track_{i}"
            self._songs_map[tid] = song
            row = TrackRow(song, tid)
            self._track_rows[tid] = row
            self._tracks_layout.insertWidget(
                self._tracks_layout.count() - 1, row
            )

        self._download_btn.setEnabled(True)
        self._open_btn.setEnabled(True)

    def _on_fetch_error(self, msg: str) -> None:
        self._status.setText(f"Error: {msg}")

    def _on_fetch_finished(self) -> None:
        self._fetch_btn.setEnabled(True)
        self._fetch_btn.setText("Fetch")

    def _clear_tracks(self) -> None:
        self._track_rows.clear()
        self._songs_map.clear()
        while self._tracks_layout.count() > 1:
            item = self._tracks_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    # ── Download ─────────────────────────────────────────────────────────────

    def _start_downloads(self) -> None:
        selected = [
            (tid, row)
            for tid, row in self._track_rows.items()
            if row.is_selected()
        ]
        if not selected:
            return

        self._total     = len(selected)
        self._completed = 0
        self._tally     = {"done": 0, "skipped": 0, "failed": 0}
        self._batch_started = time.monotonic()
        self._download_btn.setEnabled(False)
        self._download_btn.setText("Downloading...")

        self._progress_bar.setMaximum(self._total)
        self._progress_bar.setValue(0)
        self._progress_bar.show()
        self._progress_lbl.setText(f"0 / {self._total}")

        out_dir = self._output_dir / sanitize(self._playlist_name or "Playlist")
        out_dir.mkdir(parents=True, exist_ok=True)

        log(f"[PLAYLIST] Batch start: {self._total} tracks -> {out_dir} "
            f"({MAX_WORKERS} at a time)")

        for tid, row in selected:
            row.set_status("waiting")
            song = self._songs_map[tid]

            sigs = WorkerSignals()
            self._signal_refs.append(sigs)

            sigs.started.connect(lambda t:    self._on_track_started(t))
            sigs.finished.connect(lambda t:   self._on_track_done(t, "done"))
            sigs.skipped.connect(lambda t:    self._on_track_done(t, "skipped"))
            sigs.failed.connect(lambda t, _:  self._on_track_done(t, "failed"))

            worker = PlaylistTrackDownloader(
                song, out_dir, sigs, tid, audio_format_setting.value()
            )
            self._pool.start(worker)

    def _on_track_started(self, track_id: str) -> None:
        row = self._track_rows.get(track_id)
        if row:
            row.set_status("downloading")

    def _on_track_done(self, track_id: str, status: str) -> None:
        row = self._track_rows.get(track_id)
        if row:
            row.set_status(status)
        self._completed += 1
        self._tally[status] = self._tally.get(status, 0) + 1
        self._progress_bar.setValue(self._completed)

        tally = (f"{self._tally['done']} done, {self._tally['skipped']} skipped, "
                 f"{self._tally['failed']} failed")

        if self._completed >= self._total:
            elapsed = time.monotonic() - self._batch_started
            log(f"[PLAYLIST] Batch complete in {elapsed:.1f}s - {tally}")
            self._progress_lbl.setText(
                f"All done - {self._total} tracks processed"
            )
            self._download_btn.setEnabled(True)
            self._download_btn.setText("Download Selected")
        else:
            log(f"[PLAYLIST] Progress {self._completed}/{self._total} - {tally}")
            self._progress_lbl.setText(f"{self._completed} / {self._total}")

    def _open_folder(self) -> None:
        folder = (
            self._output_dir / sanitize(self._playlist_name)
            if self._playlist_name
            else self._output_dir
        )
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


class SettingsTab(QWidget):
    """Tab 3 — appearance customization, ripping behavior, and dependency updates."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._checkers: list[UpdateChecker] = []
        self._checkers_pending = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 20)
        root.setSpacing(22)

        root.addLayout(self._build_appearance_section())
        root.addLayout(self._build_ripping_section())
        root.addLayout(self._build_updates_section())
        root.addStretch()

    # ── Shared layout helpers ───────────────────────────────────────────────

    @staticmethod
    def _section_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "color: #64748b; font-size: 12px; font-weight: bold; "
            "text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        return lbl

    @staticmethod
    def _row_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #dde1f0; font-size: 13px; background: transparent;")
        lbl.setMinimumWidth(190)
        return lbl

    # ── Appearance ───────────────────────────────────────────────────────────

    def _build_appearance_section(self) -> QVBoxLayout:
        section = QVBoxLayout()
        section.setSpacing(12)
        section.addWidget(self._section_label("Appearance"))

        # Accent color
        color_row = QHBoxLayout()
        color_row.addWidget(self._row_label("Accent color"))

        self._color_swatch = QPushButton()
        self._color_swatch.setFixedSize(38, 32)
        self._color_swatch.setCursor(Qt.CursorShape.PointingHandCursor)
        self._color_swatch.clicked.connect(self._choose_color)

        self._color_hex_lbl = QLabel()
        self._color_hex_lbl.setObjectName("accentText")
        self._refresh_color_swatch(appearance_settings.accent())

        color_row.addWidget(self._color_swatch)
        color_row.addWidget(self._color_hex_lbl)
        color_row.addStretch()
        section.addLayout(color_row)

        # Text size
        size_row = QHBoxLayout()
        size_row.addWidget(self._row_label("Text size"))

        self._size_slider = QSlider(Qt.Orientation.Horizontal)
        self._size_slider.setRange(80, 140)
        self._size_slider.setFixedWidth(180)
        self._size_slider.setValue(round(appearance_settings.font_scale() * 100))
        self._size_slider.valueChanged.connect(self._on_size_changed)

        self._size_pct_lbl = QLabel(f"{self._size_slider.value()}%")
        self._size_pct_lbl.setObjectName("accentText")
        self._size_pct_lbl.setMinimumWidth(42)

        size_row.addWidget(self._size_slider)
        size_row.addWidget(self._size_pct_lbl)
        size_row.addStretch()
        section.addLayout(size_row)

        # Reset
        reset_row = QHBoxLayout()
        reset_btn = QPushButton("Reset Appearance")
        reset_btn.setObjectName("ghost")
        grow_with_content(reset_btn, 34)
        reset_btn.clicked.connect(self._reset_appearance)
        reset_row.addWidget(reset_btn)
        reset_row.addStretch()
        section.addLayout(reset_row)

        return section

    def _refresh_color_swatch(self, hex_color: str) -> None:
        self._color_swatch.setStyleSheet(
            f"background-color: {hex_color}; border-radius: 8px; border: 1px solid #2d2d44;"
        )
        self._color_hex_lbl.setText(hex_color)

    def _choose_color(self) -> None:
        chosen = QColorDialog.getColor(
            QColor(appearance_settings.accent()), self, "Choose an accent color"
        )
        if chosen.isValid():
            hex_color = chosen.name()
            appearance_settings.apply(accent=hex_color)
            self._refresh_color_swatch(hex_color)

    def _on_size_changed(self, value: int) -> None:
        self._size_pct_lbl.setText(f"{value}%")
        appearance_settings.apply(font_scale=value / 100)

    def _reset_appearance(self) -> None:
        appearance_settings.reset()
        self._refresh_color_swatch(appearance_settings.accent())
        self._size_slider.setValue(round(appearance_settings.font_scale() * 100))

    # ── Ripping ──────────────────────────────────────────────────────────────

    def _build_ripping_section(self) -> QVBoxLayout:
        section = QVBoxLayout()
        section.setSpacing(12)
        section.addWidget(self._section_label("Ripping"))

        fmt_row = QHBoxLayout()
        fmt_row.addWidget(self._row_label("Default output format"))
        fmt_combo = QComboBox()
        grow_with_content(fmt_combo, 36)
        for key, spec in AUDIO_FORMATS.items():
            fmt_combo.addItem(spec["label"], key)
            fmt_combo.setItemData(
                fmt_combo.count() - 1, spec["hint"], Qt.ItemDataRole.ToolTipRole
            )
        fmt_combo.setCurrentIndex(fmt_combo.findData(audio_format_setting.value()))
        fmt_combo.currentIndexChanged.connect(
            lambda _i: audio_format_setting.set_value(fmt_combo.currentData())
        )
        audio_format_setting.changed.connect(
            lambda fmt: fmt_combo.setCurrentIndex(fmt_combo.findData(fmt))
            if fmt_combo.findData(fmt) != fmt_combo.currentIndex() else None
        )
        fmt_row.addWidget(fmt_combo)
        fmt_row.addStretch()
        section.addLayout(fmt_row)

        workers_row = QHBoxLayout()
        workers_row.addWidget(self._row_label("Max concurrent downloads"))
        settings = QSettings("RippedRipper", "RipperGUI")
        try:
            current_workers = int(settings.value("max_workers", MAX_WORKERS))
        except (TypeError, ValueError):
            current_workers = MAX_WORKERS
        self._workers_spin = QSpinBox()
        self._workers_spin.setRange(1, 16)
        self._workers_spin.setMinimumWidth(70)
        self._workers_spin.setValue(max(1, min(16, current_workers)))
        self._workers_spin.valueChanged.connect(self._on_workers_changed)
        workers_row.addWidget(self._workers_spin)
        workers_row.addStretch()
        section.addLayout(workers_row)

        return section

    def _on_workers_changed(self, value: int) -> None:
        QThreadPool.globalInstance().setMaxThreadCount(value)
        QSettings("RippedRipper", "RipperGUI").setValue("max_workers", value)
        log(f"[SETTINGS] Max concurrent downloads set to {value}")

    # ── Updates ──────────────────────────────────────────────────────────────

    def _build_updates_section(self) -> QVBoxLayout:
        section = QVBoxLayout()
        section.setSpacing(12)
        section.addWidget(self._section_label("Dependencies"))

        managed = ", ".join(p.package for p in UPDATE_POLICIES)
        info = QLabel(f"Auto-checked once a day: {managed}")
        info.setStyleSheet("color: #55557a; font-size: 12px; background: transparent;")
        section.addWidget(info)

        btn_row = QHBoxLayout()
        self._check_updates_btn = QPushButton("Check for Updates Now")
        grow_with_content(self._check_updates_btn, 36)
        self._check_updates_btn.clicked.connect(self._check_updates_now)

        open_log_btn = QPushButton("Open Log File")
        open_log_btn.setObjectName("ghost")
        grow_with_content(open_log_btn, 36)
        open_log_btn.clicked.connect(self._open_log_file)

        btn_row.addWidget(self._check_updates_btn)
        btn_row.addWidget(open_log_btn)
        btn_row.addStretch()
        section.addLayout(btn_row)

        return section

    def _check_updates_now(self) -> None:
        self._check_updates_btn.setEnabled(False)
        self._check_updates_btn.setText("Checking...")
        log("[SETTINGS] Manual update check requested for: "
            + ", ".join(p.package for p in UPDATE_POLICIES))

        self._checkers = [UpdateChecker(policy, force=True) for policy in UPDATE_POLICIES]
        self._checkers_pending = len(self._checkers)
        for checker in self._checkers:
            checker.finished.connect(self._on_checker_finished)
            checker.start()

    def _on_checker_finished(self) -> None:
        self._checkers_pending -= 1
        if self._checkers_pending <= 0:
            self._check_updates_btn.setEnabled(True)
            self._check_updates_btn.setText("Check for Updates Now")

    def _open_log_file(self) -> None:
        log_path = BASE_DIR / "ripper_gui_launch.log"
        if log_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_path)))
        else:
            log("[SETTINGS] No log file yet — it's only created when launched "
                "via the Desktop app, not when run directly from a terminal.")


# ─── Main Window ──────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Ripper GUI")
        # Only a small floor to stop the window collapsing to something
        # unusable — otherwise fully resizable to whatever size is wanted.
        # Start size is fixed at 1000x800 regardless of how it was last left;
        # this doesn't persist across launches on purpose.
        self.setMinimumSize(480, 400)
        self.resize(1000, 800)

        pool = QThreadPool.globalInstance()
        saved_workers = QSettings("RippedRipper", "RipperGUI").value("max_workers", MAX_WORKERS)
        try:
            saved_workers = int(saved_workers)
        except (TypeError, ValueError):
            saved_workers = MAX_WORKERS
        pool.setMaxThreadCount(max(1, min(16, saved_workers)))

        central = QWidget()
        central.setObjectName("root_bg")
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)

        # ── Header ───────────────────────────────────────────────────────────
        hdr = QHBoxLayout()

        logo = QLabel("Ripper GUI")
        logo.setObjectName("appTitle")
        logo.setFont(QFont("", 24, QFont.Weight.Bold))

        hdr.addWidget(logo)
        hdr.addStretch()
        layout.addLayout(hdr)

        # ── Divider ──────────────────────────────────────────────────────────
        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet("background-color: #1e1e2f;")
        layout.addWidget(div)

        # ── Splitter for Tabs and Console ────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(splitter, stretch=1)

        # ── Tabs ─────────────────────────────────────────────────────────────
        tabs = QTabWidget()
        # "&&" escapes the ampersand — a single "&" is read as a mnemonic marker
        # and renders as a stray underline in the tab label.
        tabs.addTab(SearchTab(pool),   "Search && Rip")
        tabs.addTab(PlaylistTab(pool), "Playlist Ripper")
        tabs.addTab(SettingsTab(),     "Settings")
        splitter.addWidget(tabs)

        # ── Console ──────────────────────────────────────────────────────────
        console_container = QWidget()
        c_layout = QVBoxLayout(console_container)
        c_layout.setContentsMargins(0, 10, 0, 0)
        c_layout.setSpacing(6)

        console_lbl = QLabel("Debug Log")
        console_lbl.setStyleSheet("color: #64748b; font-size: 12px; font-weight: bold; text-transform: uppercase; letter-spacing: 1px;")
        c_layout.addWidget(console_lbl)

        self.console = QTextEdit()
        self.console.setObjectName("console")
        self.console.setReadOnly(True)
        c_layout.addWidget(self.console)

        splitter.addWidget(console_container)
        splitter.setSizes([550, 150])

        app_logger.log_msg.connect(self._append_log)
        log("Ripper GUI initialized. Ready.")

        # Non-blocking: launch happens immediately, each checker reports in
        # whenever its PyPI check + optional install finishes.
        self._update_checkers = [UpdateChecker(policy) for policy in UPDATE_POLICIES]
        for checker in self._update_checkers:
            checker.start()

    def _append_log(self, msg: str) -> None:
        self.console.append(msg)
        # Scroll to bottom
        sb = self.console.verticalScrollBar()
        sb.setValue(sb.maximum())


# ─── Entry Point ──────────────────────────────────────────────────────────────

def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Ripper GUI")
    app.setStyle("Fusion")          # consistent cross-platform base
    app.setStyleSheet(build_stylesheet(appearance_settings.accent(), appearance_settings.font_scale()))

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
