#!/usr/bin/env python3
"""
Ripper GUI
──────────
Standalone PyQt6 desktop app for:
  • Search & Rip  — search YouTube Music, download as 320kbps MP3
  • Playlist Ripper — paste a Spotify playlist URL, download all tracks

Dependencies: PyQt6, ytmusicapi, yt-dlp, spotdl
Run: python ripper_gui.py
"""

import os
import re
import sys
import json
import urllib.request
from pathlib import Path

from PyQt6.QtCore import (
    QObject, QRunnable, QSize, QThread, QThreadPool,
    Qt, pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QPalette, QIcon
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QProgressBar, QPushButton, QScrollArea,
    QSizePolicy, QTabWidget, QVBoxLayout, QWidget, QCheckBox,
    QTextEdit, QSplitter
)

from ytmusicapi import YTMusic
import yt_dlp

# ─── Constants ───────────────────────────────────────────────────────────────

BASE_DIR    = Path(__file__).parent
SEARCH_DIR  = BASE_DIR / "DJ_Search_Rips"
PLAYLIST_DIR = BASE_DIR / "Playlist_Rips"
MAX_WORKERS = 4

# spotdl's publicly bundled Spotify credentials (from their open-source repo)
SPOTDL_CLIENT_ID     = "5f573c9620494bae87890c0f08a60293"
SPOTDL_CLIENT_SECRET = "212476d9b0f3472eaa762d90b19b0ba8"


# ─── Stylesheet ──────────────────────────────────────────────────────────────

STYLE = """
* {
    font-family: -apple-system, 'SF Pro Display', 'Segoe UI', Arial, sans-serif;
    font-size: 14px;
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
    font-size: 13px;
    font-weight: 600;
}
QTabBar::tab:selected {
    background: #13131f;
    color: #8b5cf6;
    border-color: #1e1e2f;
}
QTabBar::tab:hover:!selected {
    color: #a78bfa;
    background: #1c1c2e;
}

/* ── Inputs ── */
QLineEdit {
    background-color: #1a1a2e;
    border: 1px solid #2d2d44;
    border-radius: 12px;
    padding: 12px 18px;
    color: #f8fafc;
    font-size: 14px;
    selection-background-color: #7c3aed;
}
QLineEdit:focus {
    border-color: #8b5cf6;
    background-color: #1e1e36;
}
QLineEdit::placeholder {
    color: #475569;
}

/* ── Buttons ── */
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #8b5cf6, stop:1 #6366f1);
    color: white;
    border: none;
    border-radius: 12px;
    padding: 10px 24px;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.5px;
}
QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #a78bfa, stop:1 #818cf8);
}
QPushButton:pressed {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #7c3aed, stop:1 #4f46e5);
}
QPushButton:disabled {
    background: #1e1e2f;
    color: #475569;
}
QPushButton#ghost {
    background: transparent;
    border: 1px solid #2d2d44;
    color: #818cf8;
}
QPushButton#ghost:hover {
    border-color: #8b5cf6;
    background: #1a1a2e;
    color: #a78bfa;
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
    border-color: #4f46e5;
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
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #8b5cf6, stop:1 #3b82f6);
    border-radius: 4px;
}

/* ── Checkboxes ── */
QCheckBox {
    color: #94a3b8;
    spacing: 10px;
    font-size: 13px;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 6px;
    border: 1px solid #334155;
    background: #1a1a2e;
}
QCheckBox::indicator:checked {
    background: #8b5cf6;
    border-color: #8b5cf6;
    image: none;
}
QCheckBox::indicator:disabled {
    background: #1e1e2f;
    border-color: #1e1e2f;
}

/* ── Console ── */
QTextEdit#console {
    background-color: #05050a;
    color: #10b981;
    font-family: "Menlo", "Consolas", monospace;
    font-size: 12px;
    border: 1px solid #1e1e2f;
    border-radius: 8px;
    padding: 10px;
}
"""


# ─── Utility ─────────────────────────────────────────────────────────────────

def sanitize(name: str) -> str:
    """Strip characters that are illegal in filenames."""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip()

# ─── Logger ──────────────────────────────────────────────────────────────────

class AppLogger(QObject):
    log_msg = pyqtSignal(str)

app_logger = AppLogger()

def log(msg: str):
    """Emit a log message to the console UI."""
    app_logger.log_msg.emit(msg)
    print(msg)


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
            log(f"[Search] Querying YouTube Music for '{self.query}'...")
            yt = YTMusic()
            results = yt.search(self.query, filter="songs", limit=8)
            if not results:
                results = yt.search(self.query, limit=8)
            log(f"[Search] Found {len(results)} results.")
            self.results_ready.emit(results[:8])
        except Exception as exc:
            log(f"[Search] Error: {exc}")
            self.error.emit(str(exc))


class DownloadWorker(QRunnable):
    """Downloads a single song by YouTube Music video ID via yt-dlp."""

    def __init__(
        self,
        video_id:   str,
        title:      str,
        artist:     str,
        output_dir: Path,
        signals:    WorkerSignals,
    ) -> None:
        super().__init__()
        self.video_id   = video_id
        self.title      = title
        self.artist     = artist
        self.output_dir = output_dir
        self.signals    = signals

    def run(self) -> None:
        safe_title  = sanitize(self.title)
        safe_artist = sanitize(self.artist)
        filename    = f"{safe_artist} - {safe_title}.mp3"
        log(f"[Rip] Checking if {filename} already exists...")

        if (self.output_dir / filename).exists():
            log(f"[Rip] Skipped: {filename} already exists.")
            self.signals.skipped.emit(self.video_id)
            return

        log(f"[Rip] Starting download for {self.title} by {self.artist}...")
        self.signals.started.emit(self.video_id)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        url = f"https://music.youtube.com/watch?v={self.video_id}"
        ydl_opts = {
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320",
            }],
            "outtmpl": str(self.output_dir / f"{safe_artist} - {safe_title}.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
        }

        try:
            log(f"[Rip] Running yt-dlp for video ID: {self.video_id}...")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            log(f"[Rip] Success: Downloaded {filename}.")
            self.signals.finished.emit(self.video_id)
        except Exception as exc:
            log(f"[Rip] Error downloading {self.title}: {exc}")
            self.signals.failed.emit(self.video_id, str(exc))


class PlaylistFetcher(QThread):
    """
    Fetches a Spotify playlist's track list using spotdl (no API key needed).
    Also resolves the human-readable playlist name via Spotify's public oembed.
    """
    tracks_ready   = pyqtSignal(str, list)   # (playlist_name, [Song, ...])
    status_update  = pyqtSignal(str)
    error          = pyqtSignal(str)

    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url

    def run(self) -> None:
        try:
            log(f"[Playlist] Fetching Spotify playlist info for: {self.url}...")
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
                log("[Playlist] Error: spotdl is not installed.")
                self.error.emit(
                    "spotdl is not installed.\n"
                    "Run:  pip install spotdl   (or: pip install -r requirements_gui.txt)"
                )
                return

            log(f"[Playlist] spotdl found. Extracting tracks (this may take a moment)...")
            client = Spotdl(
                client_id=SPOTDL_CLIENT_ID,
                client_secret=SPOTDL_CLIENT_SECRET,
            )
            songs = client.search([self.url])
            log(f"[Playlist] Successfully extracted {len(songs)} tracks from playlist '{playlist_name}'.")
            self.tracks_ready.emit(playlist_name, songs)

        except Exception as exc:
            log(f"[Playlist] Fatal Error during fetch: {exc}")
            self.error.emit(str(exc))


class PlaylistTrackDownloader(QRunnable):
    """
    Downloads one Spotify-sourced track by matching it on YouTube Music
    and ripping via yt-dlp — same pipeline as the search tab.
    """

    def __init__(
        self,
        song:       object,           # spotdl Song
        output_dir: Path,
        signals:    WorkerSignals,
        track_id:   str,
    ) -> None:
        super().__init__()
        self.song       = song
        self.output_dir = output_dir
        self.signals    = signals
        self.track_id   = track_id

    def run(self) -> None:
        try:
            title   = self.song.name
            artists = self.song.artists or ["Unknown"]
            # artists can be List[str] (spotdl 4.x)
            artist  = artists[0] if isinstance(artists[0], str) else str(artists[0])

            safe_title  = sanitize(title)
            safe_artist = sanitize(artist)
            filename    = f"{safe_artist} - {safe_title}.mp3"

            log(f"[{title}] Checking if {filename} already exists...")
            if (self.output_dir / filename).exists():
                log(f"[{title}] Skipped: already exists.")
                self.signals.skipped.emit(self.track_id)
                return

            self.signals.started.emit(self.track_id)
            self.output_dir.mkdir(parents=True, exist_ok=True)

            log(f"[{title}] Searching YouTube Music for best match...")
            # Search YouTube Music for the best match
            yt      = YTMusic()
            query   = f"{artist} {title}"
            results = yt.search(query, filter="songs", limit=1)
            if not results:
                results = yt.search(query, limit=1)

            if not results:
                log(f"[{title}] Failed: Not found on YouTube Music.")
                self.signals.failed.emit(self.track_id, "Not found on YouTube Music")
                return

            video_id = results[0].get("videoId")
            if not video_id:
                log(f"[{title}] Failed: No video ID found.")
                self.signals.failed.emit(self.track_id, "No video ID found")
                return

            log(f"[{title}] Found match (ID: {video_id}). Starting yt-dlp download...")
            url = f"https://music.youtube.com/watch?v={video_id}"
            ydl_opts = {
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "320",
                }],
                "outtmpl": str(self.output_dir / f"{safe_artist} - {safe_title}.%(ext)s"),
                "quiet": True,
                "no_warnings": True,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            log(f"[{title}] Success: Download complete.")
            self.signals.finished.emit(self.track_id)

        except Exception as exc:
            log(f"[{title}] Error: {exc}")
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
        self.setFixedHeight(72)

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
        self._status_lbl.setFixedWidth(88)
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_lbl.setStyleSheet("font-size: 12px; font-weight: 700; background: transparent;")

        # ── Rip button ──────────────────────────────────────────────────────
        self._rip_btn = QPushButton("Rip")
        self._rip_btn.setFixedSize(100, 38)
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
        self._icon_lbl.setFixedWidth(22)
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

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 20)
        root.setSpacing(14)

        # ── Search row ──────────────────────────────────────────────────────
        row = QHBoxLayout()
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search for a song or artist …")
        self._search_input.setFixedHeight(48)
        self._search_input.returnPressed.connect(self._do_search)

        self._search_btn = QPushButton("Search")
        self._search_btn.setFixedHeight(48)
        self._search_btn.setFixedWidth(110)
        self._search_btn.clicked.connect(self._do_search)

        row.addWidget(self._search_input, stretch=1)
        row.addWidget(self._search_btn)
        root.addLayout(row)

        # ── Status ──────────────────────────────────────────────────────────
        self._status = QLabel("Search for any track to download a 320 kbps MP3")
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
        open_btn = QPushButton("Open DJ_Search_Rips Folder")
        open_btn.setObjectName("ghost")
        open_btn.setFixedHeight(40)
        open_btn.clicked.connect(self._open_folder)
        root.addWidget(open_btn)

    # ── Private helpers ─────────────────────────────────────────────────────

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
            f"{len(results)} results found  ·  downloads -> DJ_Search_Rips/"
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

        worker = DownloadWorker(vid, title, artist, SEARCH_DIR, sigs)
        self._pool.start(worker)

    def _update_card(self, track_id: str, status: str) -> None:
        card = self._cards.get(track_id)
        if card:
            card.set_status(status)

    def _open_folder(self) -> None:
        SEARCH_DIR.mkdir(parents=True, exist_ok=True)
        os.system(f"open {str(SEARCH_DIR)!r}")


class PlaylistTab(QWidget):
    """Tab 2 — paste a Spotify playlist URL, fetch tracks, download all."""

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

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 20)
        root.setSpacing(14)

        # ── URL row ─────────────────────────────────────────────────────────
        row = QHBoxLayout()
        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText(
            "Paste Spotify playlist URL  (e.g. https://open.spotify.com/playlist/…)"
        )
        self._url_input.setFixedHeight(48)
        self._url_input.returnPressed.connect(self._fetch_playlist)

        self._fetch_btn = QPushButton("Fetch")
        self._fetch_btn.setFixedHeight(48)
        self._fetch_btn.setFixedWidth(110)
        self._fetch_btn.clicked.connect(self._fetch_playlist)

        row.addWidget(self._url_input, stretch=1)
        row.addWidget(self._fetch_btn)
        root.addLayout(row)

        # ── Status ──────────────────────────────────────────────────────────
        self._status = QLabel("Paste a Spotify playlist link to fetch and batch-download all tracks")
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
        self._progress_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._progress_lbl.setStyleSheet("color: #8b7cf8; font-size: 13px; font-weight: 700;")

        root.addWidget(self._progress_bar)
        root.addWidget(self._progress_lbl)

        # ── Bottom row ───────────────────────────────────────────────────────
        bottom = QHBoxLayout()
        self._download_btn = QPushButton("Download Selected")
        self._download_btn.setFixedHeight(44)
        self._download_btn.setEnabled(False)
        self._download_btn.clicked.connect(self._start_downloads)

        self._open_btn = QPushButton("Open Folder")
        self._open_btn.setObjectName("ghost")
        self._open_btn.setFixedHeight(44)
        self._open_btn.setFixedWidth(145)
        self._open_btn.setEnabled(False)
        self._open_btn.clicked.connect(self._open_folder)

        bottom.addWidget(self._download_btn, stretch=1)
        bottom.addWidget(self._open_btn)
        root.addLayout(bottom)

    # ── Fetch ────────────────────────────────────────────────────────────────

    def _fetch_playlist(self) -> None:
        url = self._url_input.text().strip()
        if not url or "spotify.com" not in url:
            self._status.setText("Please enter a valid Spotify playlist URL.")
            return

        self._fetch_btn.setEnabled(False)
        self._fetch_btn.setText("…")
        self._download_btn.setEnabled(False)
        self._status.setText("Connecting to Spotify …")
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
            f"->  Playlist_Rips/{sanitize(playlist_name)}/"
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
        self._download_btn.setEnabled(False)
        self._download_btn.setText("Downloading...")

        self._progress_bar.setMaximum(self._total)
        self._progress_bar.setValue(0)
        self._progress_bar.show()
        self._progress_lbl.setText(f"0 / {self._total}")

        out_dir = PLAYLIST_DIR / sanitize(self._playlist_name or "Playlist")
        out_dir.mkdir(parents=True, exist_ok=True)

        for tid, row in selected:
            row.set_status("waiting")
            song = self._songs_map[tid]

            sigs = WorkerSignals()
            self._signal_refs.append(sigs)

            sigs.started.connect(lambda t:    self._on_track_started(t))
            sigs.finished.connect(lambda t:   self._on_track_done(t, "done"))
            sigs.skipped.connect(lambda t:    self._on_track_done(t, "skipped"))
            sigs.failed.connect(lambda t, _:  self._on_track_done(t, "failed"))

            worker = PlaylistTrackDownloader(song, out_dir, sigs, tid)
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
        self._progress_bar.setValue(self._completed)
        if self._completed >= self._total:
            self._progress_lbl.setText(
                f"All done - {self._total} tracks processed"
            )
            self._download_btn.setEnabled(True)
            self._download_btn.setText("Download Selected")
        else:
            self._progress_lbl.setText(f"{self._completed} / {self._total}")

    def _open_folder(self) -> None:
        folder = (
            PLAYLIST_DIR / sanitize(self._playlist_name)
            if self._playlist_name
            else PLAYLIST_DIR
        )
        folder.mkdir(parents=True, exist_ok=True)
        os.system(f"open {str(folder)!r}")


# ─── Main Window ──────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Ripper GUI")
        self.setMinimumSize(920, 750)
        self.resize(1000, 800)

        pool = QThreadPool.globalInstance()
        pool.setMaxThreadCount(MAX_WORKERS)

        central = QWidget()
        central.setObjectName("root_bg")
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)

        # ── Header ───────────────────────────────────────────────────────────
        hdr = QHBoxLayout()

        logo = QLabel("Ripper GUI")
        logo.setFont(QFont("", 24, QFont.Weight.Bold))
        logo.setStyleSheet(
            "color: #a78bfa; letter-spacing: -0.5px; background: transparent;"
        )

        tag = QLabel("Search & Rip  ·  Spotify Playlists  ·  320 kbps MP3")
        tag.setStyleSheet("color: #64748b; font-size: 13px; font-weight: 600; background: transparent;")
        tag.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        hdr.addWidget(logo)
        hdr.addStretch()
        hdr.addWidget(tag)
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
        tabs.addTab(SearchTab(pool),   "Search & Rip")
        tabs.addTab(PlaylistTab(pool), "Playlist Ripper")
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
    app.setStyleSheet(STYLE)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
