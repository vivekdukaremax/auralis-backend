from fastapi import FastAPI, HTTPException
import yt_dlp
import traceback
import json

app = FastAPI()

@app.get("/")
def home():
    return {"status": "online"}

@app.get("/health")
def health():
    return {"service": "auralis-media", "status": "healthy"}

@app.get("/resolve")
def resolve_video(video_id: str):
    print(f"\n[DEBUG] --- RESOLVE START: {video_id} ---")
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],
                    'skip': ['dash', 'hls']
                }
            }
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # 1. Extraction
            print(f"[DEBUG] Extracting info for: {video_id}")
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            
            # 2. Diagnosis (RCA)
            print(f"[DEBUG] Object Type: {type(info)}")
            print(f"[DEBUG] Available Keys: {list(info.keys())}")
            print(f"[DEBUG] is_live: {info.get('is_live')}")
            
            # 3. Robust URL Selection
            stream_url = None
            
            # Strategy A: Check top-level 'url'
            if info.get('url'):
                print("[DEBUG] SUCCESS: Found URL at top-level")
                stream_url = info['url']
            
            # Strategy B: Check 'formats' (Most common for 500 errors)
            elif 'formats' in info:
                formats = info['formats']
                print(f"[DEBUG] 'url' missing. Inspecting {len(formats)} formats...")
                
                # Filter for audio-only streams first
                audio_only = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none']
                if audio_only:
                    # Pick highest bitrate audio
                    audio_only.sort(key=lambda x: x.get('abr', 0) or 0, reverse=True)
                    stream_url = audio_only[0].get('url')
                    print(f"[DEBUG] SUCCESS: Found best audio-only format: {audio_only[0].get('format_id')}")
                else:
                    # Fallback: Pick the absolute best remaining format
                    stream_url = formats[-1].get('url')
                    print("[DEBUG] WARNING: No audio-only. Using last available format.")

            # 4. Final Verification
            if stream_url:
                print(f"[DEBUG] --- RESOLVE SUCCESS ---")
                return {"url": stream_url}
            else:
                print("[DEBUG] --- RESOLVE FAILURE: NO URL FOUND ---")
                raise HTTPException(status_code=404, detail="No streamable URL found in yt-dlp response")

    except Exception as e:
        print("[DEBUG] !!! FATAL BACKEND ERROR !!!")
        traceback.print_exc()
        # Returns the actual error message so Android can show it
        raise HTTPException(status_code=500, detail=str(e))
