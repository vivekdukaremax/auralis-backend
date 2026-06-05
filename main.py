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
import traceback
from collections import OrderedDict
from typing import Optional

# --- Configuration ---
BACKEND_VERSION = "1.2.0-FLEX-RESOLVE"
MAX_SEARCH_RESULTS = 15
CACHE_TTL = 600
CACHE_MAX_SIZE = 100
YOUTUBE_ID_REGEX = re.compile(r"^[a-zA-Z0-9_-]{11}$")
COOKIE_PATH = "/etc/secrets/cookies.txt"

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

# --- Logic: Flexible Extraction Core ---

def fetch_resolve(vid: str):
    print(f"\n[DIAGNOSTIC] Flexible Resolve for ID: {vid}")
    temp_cookie_path = f"/tmp/cookies_{uuid.uuid4().hex}.txt"
    
    # We remove the 'format' constraint here to allow metadata to load regardless
    opts = {
        'quiet': True, 
        'no_warnings': False,
        'nocheckcertificate': True,
        'extractor_args': {'youtube': {'player_client': ['android', 'web']}}
    }
    
    if os.path.exists(COOKIE_PATH):
        try:
            shutil.copyfile(COOKIE_PATH, temp_cookie_path)
            opts['cookiefile'] = temp_cookie_path
        except Exception as e:
            print(f"[DIAGNOSTIC] ERROR: Failed to isolate cookie file: {str(e)}")

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            # Get info for ALL available formats
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
            
            formats = info.get('formats', [])
            print(f"[DIAGNOSTIC] Extracted {len(formats)} formats for {vid}")
            
            # 1. Strategy: Filter for high-quality audio-only streams (M4A/Opus)
            audio_only = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none']
            
            # Sort by Average Bitrate (abr) descending
            audio_only.sort(key=lambda x: (x.get('abr') or 0, x.get('tbr') or 0), reverse=True)
            
            selected_format = None
            
            if audio_only:
                selected_format = audio_only[0]
                print(f"[DIAGNOSTIC] Found best audio-only format: {selected_format.get('format_id')}")
            else:
                # 2. Strategy: Fallback to best format containing audio (Combined Video+Audio)
                print("[DIAGNOSTIC] No audio-only found. Falling back to combined streams.")
                with_audio = [f for f in formats if f.get('acodec') != 'none']
                if with_audio:
                    with_audio.sort(key=lambda x: x.get('tbr') or 0, reverse=True)
                    selected_format = with_audio[0]

            if selected_format:
                return {
                    "url": selected_format['url'],
                    "diagnostics": {
                        "format_id": selected_format.get('format_id'),
                        "extension": selected_format.get('ext'),
                        "total_formats": len(formats),
                        "audio_only_count": len(audio_only),
                        "selected_type": "audio-only" if selected_format in audio_only else "combined"
                    }
                }
            
            raise Exception("ERR_NO_PLAYABLE_AUDIO_FORMATS")
            
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
        "search_enabled": True,
        "resolve_enabled": True,
        "cookies_configured": os.path.exists(COOKIE_PATH)
    }

@app.get("/search")
async def search(q: str = Query(..., min_length=2)):
    rid = str(uuid.uuid4())[:8]
    start = time.time()
    q = q.strip()
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
            log_event("SEARCH", rid, start, True, f"q={q}")
            return output
    except Exception as e:
        log_event("SEARCH", rid, start, False, str(e))
        return []

@app.get("/resolve")
async def resolve(video_id: str):
    rid = str(uuid.uuid4())[:8]
    start = time.time()

    if not YOUTUBE_ID_REGEX.match(video_id):
        return JSONResponse(status_code=400, content={"error": "INVALID_ID", "message": "Malformed ID"})

    try:
        res = await run_in_threadpool(fetch_resolve, video_id)
        if res:
            log_event("RESOLVE", rid, start, True, f"id={video_id}")
            return res
        raise Exception("EXTRACTION_RETURNED_NULL")
    except Exception as e:
        log_event("RESOLVE", rid, start, False, str(e), type(e).__name__)
        return JSONResponse(status_code=500, content={
            "exception_type": type(e).__name__,
            "message": str(e),
            "cookies_applied": os.path.exists(COOKIE_PATH)
        })
