import sqlite3
import os
import threading
from fastapi import FastAPI, Request, Form, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from ytmusicapi import YTMusic
import yt_dlp

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
templates = Jinja2Templates(directory="templates")
DB_FILE = "queue.db"
SEARCH_DIR = "DJ_Search_Rips"
QUEUE_DIR = "Guest_Queue_Rips"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS requests
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  artist TEXT, 
                  song TEXT, 
                  status TEXT DEFAULT 'pending', 
                  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

init_db()

def download_song(query: str, download_dir: str):
    yt = YTMusic()
    # Find official song
    results = yt.search(query, filter="songs")
    if not results:
        results = yt.search(query)
    
    if results:
        best_match = results[0]
        video_id = best_match.get('videoId')
        if not video_id:
            print(f"Could not find videoId for {query}")
            return
            
        url = f"https://music.youtube.com/watch?v={video_id}"
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            }],
            'outtmpl': f'{download_dir}/%(title)s.%(ext)s',
            'quiet': False,
            'no_warnings': True
        }
        
        os.makedirs(download_dir, exist_ok=True)
        try:
            print(f"Starting download: {query}")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            print(f"Successfully downloaded: {query}")
        except Exception as e:
            print(f"Error downloading {query}: {e}")

@app.get("/", response_class=HTMLResponse)
async def guest_view(request: Request):
    return templates.TemplateResponse(request=request, name="guest.html")

@app.get("/dj", response_class=HTMLResponse)
async def dj_dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="dj.html")

@app.post("/api/request")
async def submit_request(artist: str = Form(...), song: str = Form(...)):
    query = f"{artist} {song}"
    yt = YTMusic()
    # Search for songs first
    results = yt.search(query, filter="songs", limit=1)
    
    final_artist = artist
    final_song = song
    
    if results:
        best_match = results[0]
        final_song = best_match.get('title', song)
        artists = best_match.get('artists', [])
        if artists:
            final_artist = ", ".join([a['name'] for a in artists])
    else:
        # Try generic search if no "songs" found
        results = yt.search(query, limit=1)
        if results:
            best_match = results[0]
            final_song = best_match.get('title', song)
            artists = best_match.get('artists', [])
            if artists and isinstance(artists, list):
                final_artist = artists[0].get('name', artist)

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO requests (artist, song, status) VALUES (?, ?, 'pending')", (final_artist, final_song))
    conn.commit()
    conn.close()
    return JSONResponse({
        "status": "success", 
        "matched_artist": final_artist, 
        "matched_song": final_song
    })

@app.get("/api/queue")
async def get_queue():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM requests ORDER BY timestamp DESC")
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return JSONResponse(rows)

@app.post("/api/update_status")
async def update_status(id: int = Form(...), status: str = Form(...), background_tasks: BackgroundTasks = BackgroundTasks()):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT artist, song FROM requests WHERE id=?", (id,))
    row = c.fetchone()
    if row:
        c.execute("UPDATE requests SET status=? WHERE id=?", (status, id))
        conn.commit()
        # If selected, trigger download
        if status == 'selected':
            query = f"{row[0]} {row[1]}"
            background_tasks.add_task(download_song, query, QUEUE_DIR)
    conn.close()
    return JSONResponse({"status": "success"})

@app.post("/api/search")
async def universal_search(query: str = Form(...)):
    yt = YTMusic()
    results = yt.search(query, filter="songs", limit=5)
    return JSONResponse(results)

@app.post("/api/download_direct")
async def download_direct(query: str = Form(...), background_tasks: BackgroundTasks = BackgroundTasks()):
    background_tasks.add_task(download_song, query, SEARCH_DIR)
    return JSONResponse({"status": "downloading"})

@app.post("/api/open_folder")
async def open_folder(folder_type: str = Form(...)):
    try:
        target = SEARCH_DIR if folder_type == "search" else QUEUE_DIR
        os.makedirs(target, exist_ok=True)
        os.system(f"open {target}")
        return JSONResponse({"status": "success"})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.post("/api/delete_request")
async def delete_request(id: int = Form(...)):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("DELETE FROM requests WHERE id=?", (id,))
        conn.commit()
        conn.close()
        return JSONResponse({"status": "success"})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.post("/api/clear_queue")
async def clear_queue():
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("DELETE FROM requests")
        conn.commit()
        conn.close()
        return JSONResponse({"status": "success"})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
