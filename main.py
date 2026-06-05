from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
import yt_dlp
import time
import uuid
import logging
import re
import traceback
from collections import OrderedDict
from typing import Optional

# --- Configuration ---
BACKEND_VERSION = "1.0.0-DIAGNOSTIC"
MAX_SEARCH_RESULTS = 15
CACHE_TTL = 600
CACHE_MAX_SIZE = 100
YOUTUBE_ID_REGEX = re.compile(r"^[a-zA-Z0-9_-]{11}$")

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

# --- Logic: Extraction Core ---
def fetch_search(q: str):
    opts = {'extract_flat': True, 'quiet': True, 'no_warnings': True, 'nocheckcertificate': True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        res = ydl.extract_info(f"ytsearch{MAX_SEARCH_RESULTS}:{q}", download=False)
        output = []
        for e in res.get('entries', []):
            if e.get('id') and e.get('title'):
                output.append({
                    "id": e['id'], "title": e['title'],
                    "artist": e.get('uploader', 'YouTube'),
                    "duration": int(e.get('duration') or 0),
                    "thumbnail": f"https://i.ytimg.com/vi/{e['id']}/hqdefault.jpg"
                })
        return output

def fetch_resolve(vid: str):
    print(f"\n[DIAGNOSTIC] Stage 1: Initializing yt-dlp for ID: {vid}")
    opts = {
        'format': 'bestaudio/best', 'quiet': True, 'no_warnings': True,
        'extractor_args': {'youtube': {'player_client': ['android', 'web']}}
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        print(f"[DIAGNOSTIC] Stage 2: Extracting Info for ID: {vid}")
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
        
        print(f"[DIAGNOSTIC] Stage 3: Parsing Formats for ID: {vid}")
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
        "search_enabled": True,
        "resolve_enabled": True
    }

@app.get("/search")
async def search(q: str = Query(..., min_length=2)):
    rid = str(uuid.uuid4())[:8]
    start = time.time()
    q = q.strip()

    cached = get_cached_search(q)
    if cached:
        log_event("SEARCH", rid, start, True, f"cache_hit q='{q}'")
        return cached

    try:
        output = await run_in_threadpool(fetch_search, q)
        set_cached_search(q, output)
        log_event("SEARCH", rid, start, True, f"q='{q}' count={len(output)}")
        return output
    except Exception as e:
        log_event("SEARCH", rid, start, False, str(e), "EXTRACTION_FAILED")
        return JSONResponse(status_code=500, content={"error": "SEARCH_FAILED", "message": "Search error"})

@app.get("/resolve")
async def resolve(video_id: str):
    rid = str(uuid.uuid4())[:8]
    start = time.time()

    if not YOUTUBE_ID_REGEX.match(video_id):
        return JSONResponse(status_code=400, content={"error": "INVALID_ID", "message": "Invalid format"})

    try:
        url = await run_in_threadpool(fetch_resolve, video_id)
        if url:
            log_event("RESOLVE", rid, start, True, f"id={video_id}")
            return {"url": url}
        raise Exception("NO_URL_FOUND")
    except Exception as e:
        # THE CAPTURE BLOCK
        print(f"\n!!! RESOLVE FAILED !!!")
        print(f"video_id={video_id}")
        print(f"request_id={rid}")
        print(f"Exception Type: {type(e).__name__}")
        print(f"Exception Message: {str(e)}")
        print("--- FULL TRACEBACK ---")
        traceback.print_exc()
        print("!!! END DIAGNOSTIC !!!\n")
        
        # Return exact error for mapping
        log_event("RESOLVE", rid, start, False, str(e), "RESOLVE_FAILED")
        return JSONResponse(status_code=404, content={
            "error": "NOT_FOUND", 
            "message": f"Diagnostics captured for ID: {video_id}. Check Render logs.",
            "retry_allowed": False
        })
