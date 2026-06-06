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
import sys
from collections import OrderedDict
from typing import Optional

# --- Configuration ---
BACKEND_VERSION = "1.2.2-DIAGNOSTIC-CLIENT-EXP"
MAX_SEARCH_RESULTS = 15
CACHE_TTL = 600
CACHE_MAX_SIZE = 100
YOUTUBE_ID_REGEX = re.compile(r"^[a-zA-Z0-9_-]{11}$")
COOKIE_PATH = "/etc/secrets/cookies.txt"

app = FastAPI()

# --- LRU Cache Implementation ---
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

def log_event(endpoint: str, rid: str, start: float, success: bool, msg: str, err_type: Optional[str] = None):
    dur = round(time.time() - start, 3)
    status = "SUCCESS" if success else "FAILURE"
    log_line = f"[{endpoint}] rid={rid} dur={dur}s status={status} msg='{msg}'"
    if err_type:
        log_line += f" err_type={err_type}"
    logger.info(log_line)

# --- Core Logic: Diagnostic Resolve ---

def fetch_resolve_diagnostic(vid: str):
    rid = str(uuid.uuid4().hex)[:8]
    temp_cookie_path = f"/tmp/cookies_{rid}.txt"
    
    # EXPERIMENT: Pivot client list to ios and mweb to find hidden streamingData
    opts = {
        'quiet': True, 
        'no_warnings': False, 
        'nocheckcertificate': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'mweb', 'android']
            }
        }
    }
    
    cookies_applied = False
    if os.path.exists(COOKIE_PATH):
        try:
            shutil.copyfile(COOKIE_PATH, temp_cookie_path)
            opts['cookiefile'] = temp_cookie_path
            cookies_applied = True
        except:
            pass

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                # User Requirement: Keep process=False exactly as is
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False, process=False)
                
                formats = info.get('formats', [])
                
                # Capture metadata for diagnostics
                formats_sample = []
                for f in formats[:20]:
                    formats_sample.append({
                        "format_id": f.get("format_id"),
                        "ext": f.get("ext"),
                        "acodec": f.get("acodec"),
                        "vcodec": f.get("vcodec"),
                        "abr": f.get("abr"),
                        "tbr": f.get("tbr")
                    })

                return {
                    "yt_dlp_version": yt_dlp.version.__version__,
                    "cookies_applied": cookies_applied,
                    "title": info.get("title"),
                    "extractor": info.get("extractor"),
                    "total_formats": len(formats),
                    "first_20_ids": [f.get("format_id") for f in formats[:20]],
                    "formats_sample": formats_sample
                }
            except Exception as e:
                return {
                    "diagnostic_error_type": type(e).__name__,
                    "diagnostic_error_message": str(e),
                    "yt_dlp_version": yt_dlp.version.__version__,
                    "cookies_applied": cookies_applied,
                    "traceback": traceback.format_exc()
                }
    finally:
        if os.path.exists(temp_cookie_path):
            try:
                os.remove(temp_cookie_path)
            except:
                pass

# --- API Endpoints ---

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
    rid = str(uuid.uuid4().hex)[:8]
    start = time.time()
    q = q.strip()
    cached = get_cached_search(q)
    if cached:
        return cached

    try:
        opts = {'extract_flat': True, 'quiet': True, 'no_warnings': True}
        def execute_search():
            with yt_dlp.YoutubeDL(opts) as ydl:
                res = ydl.extract_info(f"ytsearch{MAX_SEARCH_RESULTS}:{q}", download=False)
                return [
                    {
                        "id": e['id'], 
                        "title": e['title'], 
                        "artist": e.get('uploader', 'YouTube'), 
                        "duration": int(e.get('duration') or 0), 
                        "thumbnail": f"https://i.ytimg.com/vi/{e['id']}/hqdefault.jpg"
                    } for e in res.get('entries', []) if e.get('id')
                ]
        
        output = await run_in_threadpool(execute_search)
        set_cached_search(q, output)
        log_event("SEARCH", rid, start, True, f"q='{q}'")
        return output
    except Exception as e:
        log_event("SEARCH", rid, start, False, str(e), type(e).__name__)
        return []

@app.get("/resolve")
async def resolve(video_id: str):
    rid = str(uuid.uuid4().hex)[:8]
    start = time.time()

    if not YOUTUBE_ID_REGEX.match(video_id):
        return JSONResponse(status_code=400, content={"error": "INVALID_ID", "message": "Malformed ID"})

    try:
        res = await run_in_threadpool(fetch_resolve_diagnostic, video_id)
        log_event("RESOLVE_DIAG", rid, start, True, f"id={video_id}")
        return res
    except Exception as e:
        log_event("RESOLVE_DIAG", rid, start, False, str(e), type(e).__name__)
        return JSONResponse(status_code=500, content={
            "error": type(e).__name__,
            "message": str(e)
        })

@app.get("/debug-resolve")
async def debug_resolve(video_id: str):
    return await resolve(video_id)
