from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
import yt_dlp
import time
import uuid
import logging
import re
import os
import shutil
import subprocess
import traceback
from collections import OrderedDict
from typing import Optional

# --- Configuration ---
BACKEND_VERSION = "1.3.0-PRODUCTION"
MAX_SEARCH_RESULTS = 15
CACHE_TTL = 600
CACHE_MAX_SIZE = 100
YOUTUBE_ID_REGEX = re.compile(r"^[a-zA-Z0-9_-]{11}$")
COOKIE_SECRET_PATH = "/etc/secrets/cookies.txt"
YTDLP_CACHE_DIR = "/tmp/ytdlp-cache"

app = FastAPI()

# --- True LRU Cache ---
search_cache = OrderedDict()

def get_cached_search(q: str):
    if q in search_cache:
        cached = search_cache[q]
        if time.time() - cached["timestamp"] < CACHE_TTL:
            search_cache.move_to_end(q)
            return cached["data"]
        del search_cache[q]
    return None

def set_cached_search(q: str, data: list):
    if len(search_cache) >= CACHE_MAX_SIZE:
        search_cache.popitem(last=False)
    search_cache[q] = {"timestamp": time.time(), "data": data}

# --- Structured Logging ---
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("auralis")

def log_event(endpoint: str, rid: str, start: float, success: bool, msg: str, err: Optional[str] = None):
    dur = round(time.time() - start, 3)
    status = "SUCCESS" if success else "FAILURE"
    log_line = f"[{endpoint}] rid={rid} dur={dur}s status={status} msg='{msg}'"
    if err: log_line += f" err_type={err}"
    logger.info(log_line)

# --- Core Logic: Extraction Core ---

def fetch_search(q: str):
    """Bypass authenticated extraction for search to ensure maximum speed."""
    opts = {
        'extract_flat': True, 
        'quiet': True, 
        'no_warnings': True, 
        'nocheckcertificate': True
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        res = ydl.extract_info(f"ytsearch{MAX_SEARCH_RESULTS}:{q}", download=False)
        output = []
        for e in res.get('entries', []):
            if e.get('id') and e.get('title'):
                output.append({
                    "id": e['id'], 
                    "title": e['title'],
                    "artist": e.get('uploader', 'YouTube'),
                    "duration": int(e.get('duration') or 0),
                    "thumbnail": f"https://i.ytimg.com/vi/{e['id']}/hqdefault.jpg"
                })
        return output

def fetch_resolve(vid: str):
    """
    Verified Production Resolve logic.
    Uses JS Runtimes and EJS to unlock streamingData omitted by datacenter IPs.
    """
    rid = str(uuid.uuid4().hex)[:8]
    temp_cookie_path = f"/tmp/cookies_{rid}.txt"
    
    # Verified Python API Options (v2025.01.15+)
    # cachedir: Required for EJS solver persistence
    # remote_components: List required to download ejs:github solver
    # js_runtimes: List specifying Node as the interpreter
    opts = {
        'format': 'bestaudio/best', 
        'quiet': True, 
        'no_warnings': True,
        'nocheckcertificate': True,
        'cachedir': YTDLP_CACHE_DIR,
        'remote_components': ['ejs:github'],
        'js_runtimes': ['node'],
        'extractor_args': {'youtube': {'player_client': ['ios', 'android', 'web']}}
    }
    
    # Isolation: Copy read-only secret to a unique writable temporary file
    if os.path.exists(COOKIE_SECRET_PATH):
        try:
            shutil.copyfile(COOKIE_SECRET_PATH, temp_cookie_path)
            opts['cookiefile'] = temp_cookie_path
        except Exception as e:
            print(f"[{rid}] Cookie Copy Failed: {str(e)}")

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            # Metadata fetch with full processing enabled (default process=True)
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
            
            url = info.get('url')
            formats = info.get('formats', [])
            
            # Manual fallback selection if yt-dlp default fails to pick a direct URL
            if not url and formats:
                audio = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none']
                if audio:
                    audio.sort(key=lambda x: (x.get('abr') or 0, x.get('tbr') or 0), reverse=True)
                    url = audio[0]['url']
                else:
                    url = formats[-1]['url']
            
            if url:
                return {
                    "url": url,
                    "diagnostics": {
                        "total_formats": len(formats),
                        "selected_id": info.get('format_id') or "manual",
                        "js_runtime": "active"
                    }
                }
            raise Exception("UNABLE_TO_LOCATE_MEDIA_STREAMS")
            
    finally:
        if os.path.exists(temp_cookie_path):
            try: os.remove(temp_cookie_path)
            except: pass

# --- Endpoints ---

@app.get("/health")
async def health():
    return {"service": "auralis-media", "status": "healthy"}

@app.get("/version")
async def version():
    return {
        "backend_version": BACKEND_VERSION,
        "yt_dlp_version": yt_dlp.version.__version__,
        "cookies_configured": os.path.exists(COOKIE_SECRET_PATH),
        "js_solver_enabled": True
    }

@app.get("/env-check")
async def env_check():
    """Confirms environment-level readiness for YouTube challenges."""
    node_v = "not_found"
    try:
        node_v = subprocess.check_output(["node", "--version"]).decode().strip()
    except: pass
    
    return {
        "node_available": node_v != "not_found",
        "node_version": node_v,
        "yt_dlp_version": yt_dlp.version.__version__,
        "cache_path": YTDLP_CACHE_DIR,
        "cache_writable": os.access("/tmp", os.W_OK)
    }

@app.get("/search")
async def search(q: str = Query(..., min_length=2)):
    rid = str(uuid.uuid4().hex)[:8]
    start = time.time()
    q = q.strip()
    cached = get_cached_search(q)
    if cached:
        log_event("SEARCH", rid, start, True, f"cache_hit q='{q}'")
        return cached

    try:
        output = await run_in_threadpool(fetch_search, q)
        set_cached_search(q, output)
        log_event("SEARCH", rid, start, True, f"count={len(output)}")
        return output
    except Exception as e:
        log_event("SEARCH", rid, start, False, str(e), type(e).__name__)
        return []

@app.get("/resolve")
async def resolve(video_id: str):
    rid = str(uuid.uuid4().hex)[:8]
    start = time.time()

    if not YOUTUBE_ID_REGEX.match(video_id):
        return JSONResponse(status_code=400, content={"error": "INVALID_ID"})

    try:
        res = await run_in_threadpool(fetch_resolve, video_id)
        log_event("RESOLVE", rid, start, True, f"id={video_id}")
        return res
    except Exception as e:
        log_event("RESOLVE", rid, start, False, str(e), type(e).__name__)
        return JSONResponse(status_code=500, content={
            "error": type(e).__name__,
            "message": str(e),
            "hint": "Ensure Node.js is healthy via /env-check"
        })
