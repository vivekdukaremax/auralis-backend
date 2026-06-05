from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
import yt_dlp
import time
import uuid
import logging
import re
import os
from collections import OrderedDict
from typing import Optional

# --- Configuration ---
BACKEND_VERSION = "1.0.1-DIAG"
MAX_SEARCH_RESULTS = 15
CACHE_TTL = 600
CACHE_MAX_SIZE = 100
YOUTUBE_ID_REGEX = re.compile(r"^[a-zA-Z0-9_-]{11}$")
COOKIE_PATH = "/etc/secrets/cookies.txt"

app = FastAPI()

# --- True LRU Cache (UNCHANGED) ---
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

# --- Logic: Extraction Core (Minimal Resolve Patch) ---

def fetch_resolve(vid: str):
    # DIAGNOSTIC LOGS
    print(f"\n[DIAGNOSTIC] Resolving ID: {vid}")
    print(f"[DIAGNOSTIC] yt-dlp version: {yt_dlp.version.__version__}")
    
    file_exists = os.path.exists(COOKIE_PATH)
    file_readable = os.access(COOKIE_PATH, os.R_OK) if file_exists else False
    print(f"[DIAGNOSTIC] Cookie File: exists={file_exists}, readable={file_readable}")

    opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': False,
        'nocheckcertificate': True,
        'extractor_args': {'youtube': {'player_client': ['android', 'web']}}
    }
    
    if file_exists and file_readable:
        opts['cookiefile'] = COOKIE_PATH
        print("[DIAGNOSTIC] yt-dlp: 'cookiefile' option successfully added to opts.")
    else:
        print("[DIAGNOSTIC] WARNING: yt-dlp: Running WITHOUT cookies (file missing or unreadable).")

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
        url = info.get('url')
        if not url and 'formats' in info:
            audio = [f for f in info['formats'] if f.get('acodec') != 'none' and f.get('vcodec') == 'none']
            if audio:
                audio.sort(key=lambda x: x.get('abr', 0) or 0, reverse=True)
                url = audio[0]['url']
        return url

# --- Endpoints ---

@app.get("/health")
async def health():
    return {"service": "auralis-media", "status": "healthy"}

@app.get("/version")
async def version():
    return {
        "backend_version": BACKEND_VERSION,
        "cookies_present": os.path.exists(COOKIE_PATH),
        "cookies_readable": os.access(COOKIE_PATH, os.R_OK) if os.path.exists(COOKIE_PATH) else False
        "cookie_path": COOKIE_PATH
    }

@app.get("/search")
async def search(q: str = Query(..., min_length=2)):
    # SEARCH LOGIC UNCHANGED
    cached = get_cached_search(q)
    if cached: return cached
    try:
        opts = {'extract_flat': True, 'quiet': True, 'no_warnings': True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            res = ydl.extract_info(f"ytsearch{MAX_SEARCH_RESULTS}:{q}", download=False)
            output = []
            for e in res.get('entries', []):
                if e.get('id'):
                    output.append({"id": e['id'], "title": e['title'], "artist": e.get('uploader', 'YouTube'), "duration": int(e.get('duration') or 0), "thumbnail": f"https://i.ytimg.com/vi/{e['id']}/hqdefault.jpg"})
            set_cached_search(q, output)
            return output
    except Exception: return []

@app.get("/resolve")
async def resolve(video_id: str):
    if not YOUTUBE_ID_REGEX.match(video_id):
        return JSONResponse(status_code=400, content={"error": "INVALID_ID", "message": "Malformed ID"})

    try:
        url = await run_in_threadpool(fetch_resolve, video_id)
        if url:
            return {"url": url}
        raise Exception("NO_URL_RETURNED")
    except Exception as e:
        # RETURN REAL EXCEPTION FOR ANALYSIS
        return JSONResponse(status_code=500, content={
            "exception_type": type(e).__name__,
            "message": str(e),
            "cookies_applied": os.path.exists(COOKIE_PATH)
        })
