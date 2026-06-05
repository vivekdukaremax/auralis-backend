from fastapi import FastAPI, HTTPException
import yt_dlp

app = FastAPI()

@app.get("/")
def home():
    return {"status": "online"}

@app.get("/health")
def health():
    return {"service": "auralis-media", "status": "healthy"}

@app.get("/resolve")
def resolve_video(video_id: str):
    try:
        # These PRO settings make the backend look like a real Android app
        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'source_address': '0.0.0.0',
            'nocheckcertificate': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],
                    'skip': ['dash', 'hls']
                }
            }
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            return {"url": info['url']}
    except Exception as e:
        # This will tell us EXACTLY why it failed in the logs
        print(f"Extraction Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
