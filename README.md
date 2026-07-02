# Ripped Ripper

A professional, automated music request and management system designed for live DJ sets. Ripped Ripper allows guests to submit song requests via a web interface, which the DJ can then search, download, and manage in real-time. It also includes a standalone desktop application for quickly ripping YouTube Music search results and full Spotify playlists.

## Features

- **Guest Request Portal**: A sleek, mobile-friendly interface for guests to submit song and artist requests.
- **DJ Dashboard (Web)**: A powerful split-screen management console for the DJ to process guest requests.
- **Standalone Desktop GUI**: A sleek native application built with PyQt6 for standalone music acquisition.
- **Spotify Playlist Ripping**: Paste a Spotify playlist link in the Desktop GUI to automatically fetch and rip all tracks.
- **Universal Search**: Real-time search across YouTube Music to find any requested track.
- **Automated Ripping**: One-click downloading and conversion of songs to high-quality MP3s using `yt-dlp`.

## Tech Stack

- **Backend**: FastAPI (Python)
- **Database**: SQLite
- **Frontend**: HTML5, Vanilla CSS3, JavaScript
- **Desktop GUI**: PyQt6
- **Integrations**: `yt-dlp`, `ytmusicapi`, `spotdl`

## Getting Started

There are two ways to use Ripped Ripper depending on your needs.

### 1. Web-based DJ System (With Guest Requests)
This mode runs a local web server with a management dashboard for the DJ, and generates a public link for guests to request songs.

1. **Install Web Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
2. **Run the System**:
   Use the provided startup script to launch the backend and dashboard:
   ```bash
   ./start_dj.sh
   ```
3. **Guest Access**:
   Provide the Ngrok tunnel URL (generated at startup) to your guests.

### 2. Standalone Desktop GUI (Search & Spotify Playlists)
This mode runs a standalone native application where you can manually search for songs or paste Spotify playlists to batch-download them.

1. **Install GUI Dependencies**:
   ```bash
   pip install -r requirements_gui.txt
   ```
2. **Run the App**:
   ```bash
   python ripper_gui.py
   ```

## Authors

- **John Tamayo**
- **Tanner Hochberg**

---
*Built for DJs who want to spend more time mixing and less time searching.*
