from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
import yt_dlp
import time
import uuid
import logging
import re
from collections import OrderedDict
from typing import Optional

# --- Configuration ---
BACKEND_VERSION = "1.0.0"
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
    opts = {
        'format': 'bestaudio/best', 'quiet': True, 'no_warnings': True,
        'extractor_args': {'youtube': {'player_client': ['android', 'web']}}
    }
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
    start = time.time()
    rid = str(uuid.uuid4())[:8]
    log_event("HEALTH", rid, start, True, "service healthy")
    return {"service": "auralis-media", "status": "healthy"}

@app.get("/version")
async def version():
    start = time.time()
    rid = str(uuid.uuid4())[:8]
    log_event("VERSION", rid, start, True, f"v{BACKEND_VERSION}")
    return {"backend_version": BACKEND_VERSION, "search_enabled": True, "resolve_enabled": True}

@app.get("/search")
async def search(q: str = Query(..., min_length=2, max_length=100)):
    rid = str(uuid.uuid4())[:8]
    start = time.time()
    q = q.strip()

    cached = get_cached_search(q)
    if cached:
        log_event("SEARCH", rid, start, True, f"cache_hit q='{q}'")
        return cached

    try:
        # Run the blocking yt-dlp call in a separate threadpool
        output = await run_in_threadpool(fetch_search, q)
        set_cached_search(q, output)
        log_event("SEARCH", rid, start, True, f"q='{q}' count={len(output)}")
        return output
    except Exception as e:
        log_event("SEARCH", rid, start, False, str(e), "EXTRACTION_FAILED")
        return JSONResponse(status_code=500, content={"error": "SEARCH_FAILED", "message": "YouTube search timed out.", "retry_allowed": True})

@app.get("/resolve")
async def resolve(video_id: str):
    rid = str(uuid.uuid4())[:8]
    start = time.time()

    if not YOUTUBE_ID_REGEX.match(video_id):
        log_event("RESOLVE", rid, start, False, "invalid video id format", "INVALID_ID")
        return JSONResponse(status_code=400, content={"error": "INVALID_ID", "message": "Invalid YouTube ID format", "retry_allowed": False})

    try:
        url = await run_in_threadpool(fetch_resolve, video_id)
        if url:
            log_event("RESOLVE", rid, start, True, f"id={video_id}")
            return {"url": url}
        raise Exception("NO_URL")
    except Exception as e:
        log_event("RESOLVE", rid, start, False, str(e), "RESOLVE_FAILED")
        return JSONResponse(status_code=404, content={"error": "NOT_FOUND", "message": "Video is private or missing audio.", "retry_allowed": False})
