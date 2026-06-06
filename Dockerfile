# 1. Use Python 3.11 Slim for a lightweight base
FROM python:3.11-slim

# 2. Install system dependencies
# ffmpeg: Required for audio post-processing and ITAG extraction
# curl: Required to fetch the Node.js installation script
# nodejs: The JavaScript runtime required by yt-dlp to solve YouTube challenges
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# 3. Set the working directory
WORKDIR /app

# 4. Create a writable cache directory for yt-dlp
# This is required for the EJS challenge solver to download and persist components
RUN mkdir -p /tmp/ytdlp-cache && chmod 777 /tmp/ytdlp-cache

# 5. Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 6. Copy application code
COPY . .

# 7. Start the server via Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]
