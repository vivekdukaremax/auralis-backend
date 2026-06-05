from fastapi import FastAPI, Header, HTTPException, Request
import os

app = FastAPI(
    title="Auralis Backend",
    version="1.0.0"
)

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


@app.get("/headers")
async def headers(request: Request):
    return {
        "headers": dict(request.headers)
    }


@app.get("/secure-test")
async def secure_test(request: Request):

    received_header = request.headers.get("authorization")

    expected_header = f"Bearer {API_KEY}"

    print("\n")
    print("=" * 50)
    print("RECEIVED:", repr(received_header))
    print("EXPECTED:", repr(expected_header))
    print("=" * 50)
    print("\n")

    if received_header != expected_header:
        raise HTTPException(
            status_code=401,
            detail={
                "message": "Invalid API Key",
                "received": received_header,
                "expected": expected_header
            }
        )

    return {
        "message": "Authentication successful",
        "received": received_header
    }
