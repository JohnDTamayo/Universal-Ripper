# Ripped Ripper

Automated music request and ripping toolkit for live DJ sets. Guests submit song requests through a web portal; the DJ searches, rips, and manages tracks in real time. Includes a standalone desktop app for search-based ripping and full Spotify/Apple Music playlist downloads.

## Features

- **Guest Request Portal** — mobile-friendly page for guests to submit song requests
- **DJ Dashboard** — web console for the DJ to process requests in real time
- **Desktop GUI** — native PyQt6 app for search-and-rip or playlist batch downloads
- **Playlist Ripping** — paste a Spotify or Apple Music playlist link to fetch and rip every track
- **Universal Search** — real-time YouTube Music search for any track
- **320kbps MP3s** — automated download and conversion via `yt-dlp`
- **Custom Save Location** — choose or create any folder as the download destination

## Tech Stack

- **Backend**: FastAPI (Python) · SQLite
- **Frontend**: HTML5, CSS3, JavaScript
- **Desktop GUI**: PyQt6
- **Integrations**: `yt-dlp`, `ytmusicapi`, `spotdl`

## Getting Started

### 0. Clone

```bash
git clone https://github.com/JohnDTamayo/Universal-Ripper.git ripped_ripper
cd ripped_ripper
```

> **macOS**: clone outside `~/Desktop`, `~/Documents`, or `~/Downloads` — macOS blocks the Desktop app shortcut from reading files in those folders.

### 1. Web-based DJ System

```bash
pip install -r requirements.txt
./start_dj.sh
```
Share the generated Ngrok URL with your guests.

### 2. Standalone Desktop GUI

**First-time setup** (creates the virtual environment, installs dependencies, and adds a Desktop shortcut):
- macOS: double-click `setup_mac.command`
- Windows: double-click `setup_win.bat`

**Launch afterward**:
- macOS: `launch_gui.command`, or the **Ripped Ripper** app on your Desktop
- Windows: `launch_gui.bat`, or the **Ripped Ripper** shortcut on your Desktop

## Authors

John Tamayo · Tanner Hochberg

---
*Built for DJs who want to spend more time mixing and less time searching.*
