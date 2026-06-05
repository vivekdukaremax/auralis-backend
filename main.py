from fastapi import FastAPI, Header, HTTPException
import os

app = FastAPI()

API_KEY = os.getenv("API_KEY")

@app.get("/")
def home():
    return {"status": "online"}

@app.get("/health")
def health():
    return {
        "service": "auralis-backend",
        "status": "healthy"
    }

@app.get("/secure-test")
def secure_test(authorization: str = Header(None)):
    
    if authorization != f"Bearer {API_KEY}":
        raise HTTPException(
            status_code=401,
            detail="Invalid API Key"
        )

    return {
        "message": "Authentication successful"
    }
