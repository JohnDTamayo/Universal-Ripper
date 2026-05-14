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
import asyncio
import json
from fastapi.responses import StreamingResponse

import subprocess
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    global loop
    loop = asyncio.get_running_loop()
    print("Event loop captured for SSE")
    yield
    subscribers.clear()

app = FastAPI(lifespan=lifespan)

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

# SSE Notification System
subscribers = set()
loop = None


async def broadcast(data):
    if not subscribers:
        return
    print(f"Broadcasting event: {data}")
    message = f"data: {json.dumps(data)}\n\n"
    for q in list(subscribers):
        await q.put(message)

def init_db():
    conn = sqlite3.connect(DB_FILE, timeout=10)
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

def download_song(query: str, download_dir: str, request_id: int = None):
    try:
        yt = YTMusic()
        # Find official song
        results = yt.search(query, filter="songs")
        if not results:
            results = yt.search(query)
        
        if not results:
            raise Exception(f"No results found for: {query}")

        best_match = results[0]
        video_id = best_match.get('videoId')
        if not video_id:
            raise Exception(f"Could not find videoId for {query}")
            
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
        print(f"Starting download: {query}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        print(f"Successfully downloaded: {query}")
        
        # Update database if this was a queue request
        if request_id:
            conn = sqlite3.connect(DB_FILE, timeout=10)
            c = conn.cursor()
            c.execute("UPDATE requests SET status='downloaded' WHERE id=?", (request_id,))
            conn.commit()
            conn.close()

        # Notify clients
        notification = {
            "event": "download_complete",
            "query": query,
            "request_id": request_id,
            "status": "success"
        }
        asyncio.run_coroutine_threadsafe(broadcast(notification), loop)

    except Exception as e:
        print(f"Error downloading {query}: {e}")
        notification = {
            "event": "download_failed",
            "query": query,
            "request_id": request_id,
            "status": "error",
            "message": str(e)
        }
        asyncio.run_coroutine_threadsafe(broadcast(notification), loop)

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
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM requests ORDER BY timestamp DESC")
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return JSONResponse(rows)

@app.post("/api/update_status")
async def update_status(id: int = Form(...), status: str = Form(...), background_tasks: BackgroundTasks = BackgroundTasks()):
    conn = sqlite3.connect(DB_FILE, timeout=10)
    c = conn.cursor()
    c.execute("SELECT artist, song FROM requests WHERE id=?", (id,))
    row = c.fetchone()
    if row:
        c.execute("UPDATE requests SET status=? WHERE id=?", (status, id))
        conn.commit()
        # If selected, trigger download
        if status == 'selected':
            query = f"{row[0]} {row[1]}"
            background_tasks.add_task(download_song, query, QUEUE_DIR, id)
    conn.close()
    return JSONResponse({"status": "success"})

@app.get("/api/events")
async def events(request: Request):
    async def event_generator():
        q = asyncio.Queue()
        subscribers.add(q)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    # Use a timeout so we can check for disconnection
                    message = await asyncio.wait_for(q.get(), timeout=1.0)
                    yield message
                except asyncio.TimeoutError:
                    continue
        finally:
            subscribers.discard(q)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

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
        subprocess.run(["open", target])
        return JSONResponse({"status": "success"})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.post("/api/delete_request")
async def delete_request(id: int = Form(...)):
    try:
        conn = sqlite3.connect(DB_FILE, timeout=10)
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
        conn = sqlite3.connect(DB_FILE, timeout=10)
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
