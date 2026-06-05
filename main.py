from fastapi import FastAPI, Header, HTTPException
import os

app = FastAPI()

API_KEY = os.getenv("API_KEY")

print("=" * 50)
print("API_KEY LOADED:", repr(API_KEY))
print("=" * 50)


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


@app.get("/debug")
def debug():
    return {
        "api_key_loaded": API_KEY is not None,
        "api_key_value": API_KEY,
        "api_key_length": len(API_KEY) if API_KEY else 0
    }


@app.get("/secure-test")
def secure_test(authorization: str = Header(None)):

    expected_header = f"Bearer {API_KEY}"

    print("Received Header:", repr(authorization))
    print("Expected Header:", repr(expected_header))

    if authorization != expected_header:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "Invalid API Key",
                "received": authorization,
                "expected": expected_header
            }
        )

    return {
        "message": "Authentication successful"
    }
