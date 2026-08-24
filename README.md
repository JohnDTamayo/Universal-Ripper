# Ripped Ripper

Automated music request and ripping toolkit for live DJ sets. Guests submit song requests through a web portal; the DJ searches, rips, and manages tracks in real time. Includes a standalone desktop app for search-based ripping and full Spotify/Apple Music playlist downloads.

## Features

- **Guest Request Portal** — mobile-friendly page for guests to submit song requests
- **DJ Dashboard** — web console for the DJ to process requests in real time
- **Desktop GUI** — native PyQt6 app for search-and-rip or playlist batch downloads
- **Playlist Ripping** — paste a Spotify or Apple Music playlist link to fetch and rip every track
- **Universal Search** — real-time YouTube Music search for any track
- **Choose Your Format** — rip to MP3, M4A, FLAC or WAV; all four load in Traktor, Serato, Rekordbox and VirtualDJ
- **Parallel Ripping** — up to 8 tracks at once, with retry/backoff when YouTube throttles
- **Custom Save Location** — choose or create any folder as the download destination

## Tech Stack

- **Backend**: FastAPI (Python) · SQLite
- **Frontend**: HTML5, CSS3, JavaScript
- **Desktop GUI**: PyQt6
- **Integrations**: `yt-dlp`, `ytmusicapi`, `spotdl`

## Install (no setup required)

Prebuilt standalone apps — Python, ffmpeg, and all dependencies included:

**[⬇ Download page](https://johndtamayo.github.io/Universal-Ripper/)** · or grab a file directly from [Releases](https://github.com/JohnDTamayo/Universal-Ripper/releases/latest)

| Platform | File |
|---|---|
| macOS (Apple Silicon) | `RippedRipper-macOS.dmg` |
| Windows (64-bit) | `RippedRipper-Windows.zip` |

These builds aren't code-signed, so the first launch needs one extra step: on macOS right-click the app → **Open** (then *System Settings → Privacy & Security → Open Anyway* if still blocked); on Windows click **More info** → **Run anyway** at the SmartScreen prompt.

Rips default to `~/Music/Ripped Ripper`, changeable in-app.

## Building from source

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

**Output format** — pick one from the `Format` dropdown; the choice is remembered and applies to both tabs.

| Format | Size / track | Notes |
|---|---|---|
| MP3 | ~9 MB | 320 kbps, widest compatibility (default) |
| M4A | ~4 MB | AAC copied as-is — no re-encode, fastest |
| FLAC | ~24 MB | Lossless container, 16-bit |
| WAV | ~44 MB | Lossless, no metadata support |

The source is YouTube Music's ~129 kbps stream, which is the quality ceiling for every option. M4A copies that stream untouched; the others re-encode it, and the lossless formats store the same lossy audio in a much larger file rather than recovering anything.

## Publishing a release

Installers are built by GitHub Actions ([`build-installers.yml`](.github/workflows/build-installers.yml)) — macOS and Windows each build on their own runner, since neither can cross-compile the other.

```bash
git tag v1.0.0
git push origin v1.0.0
```

That builds both platforms, runs `--selftest` on each (a real download + convert inside the packaged app, so a build that can't find its own bundled ffmpeg fails CI instead of shipping), and publishes a Release with both files attached. Use **Run workflow** on the Actions tab to test a build without publishing.

The download page lives in [`docs/`](docs/index.html) and is served by GitHub Pages (enable it once under *Settings → Pages → Source: main / docs*). Its buttons point at `releases/latest/download/...`, so they keep working for new versions without edits.

To build locally: `pip install pyinstaller`, place static `ffmpeg`/`ffprobe` binaries in `packaging/ffmpeg_bin/`, then `pyinstaller --noconfirm --clean packaging/RippedRipper.spec`.

## Authors

John Tamayo · Tanner Hochberg

---
*Built for DJs who want to spend more time mixing and less time searching.*
