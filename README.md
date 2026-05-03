# Ripped Ripper

A professional, automated music request and management system designed for live DJ sets. Ripped Ripper allows guests to submit song requests via a web interface, which the DJ can then search, download, and manage in real-time.

## Features

- **Guest Request Portal**: A sleek, mobile-friendly interface for guests to submit song and artist requests.
- **DJ Dashboard**: A powerful split-screen management console for the DJ.
- **Universal Search**: Real-time search across YouTube Music to find any requested track.
- **Automated Ripping**: One-click downloading and conversion of songs to high-quality MP3s using `yt-dlp`.
- **Queue Management**: Full control over the guest queue, including the ability to select tracks for download, delete individual requests, or clear the entire queue.
- **Live Sync**: Automated polling ensures the DJ always sees the latest requests without refreshing.

## Tech Stack

- **Backend**: FastAPI (Python)
- **Database**: SQLite
- **Frontend**: HTML5, Vanilla CSS3, JavaScript
- **Integrations**: `yt-dlp`, `ytmusicapi`

## Getting Started

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the System**:
   Use the provided startup script to launch the backend and management dashboard:
   ```bash
   ./start_dj.sh
   ```

3. **Guest Access**:
   Provide the Ngrok tunnel URL (generated at startup) to your guests.

## Authors

- **John Tamayo**
- **Tanner Hochberg**

---
*Built for DJs who want to spend more time mixing and less time searching.*
