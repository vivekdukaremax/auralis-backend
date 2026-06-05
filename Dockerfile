# 1. Start with Python
FROM python:3.11-slim

# 2. Install ffmpeg (This is the secret tool needed for music)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 3. Set the working folder
WORKDIR /app

# 4. Copy your list of requirements and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy all your code into the container
COPY . .

# 6. Start the server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]
