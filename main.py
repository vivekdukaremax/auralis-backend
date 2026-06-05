from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def home():
    return {
        "status": "online"
    }

@app.get("/health")
def health():
    return {
        "service": "auralis-backend",
        "status": "healthy"
    }
