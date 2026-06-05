from fastapi import FastAPI, HTTPException
import yt_dlp

app = FastAPI()

@app.get("/")
def home():
    return {"status": "online"}

@app.get("/health")
def health():
    return {
        "service": "auralis-backend",
        "status": "healthy"
    }

# This is the new "Magic" part that finds the high-quality music link
@app.get("/resolve")
def resolve_video(video_id: str):
    try:
        ydl_opts = {
            'format': 'bestaudio/best', # Tells it we only want the best audio
            'quiet': True,
            'no_warnings': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # It goes to YouTube, finds the direct link, and gives it back to the app
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            return {"url": info['url']}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
