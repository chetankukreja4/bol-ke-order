FROM python:3.12-slim

# ffmpeg cuts long recordings into 25 s chunks for speech-to-text
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static
COPY tests ./tests
COPY scripts ./scripts

# Local Hindi voice for the spoken read-back (Piper hi_IN pratham, ~64 MB). No key, no per-order cost.
# If the download fails (no internet to Hugging Face), the build still finishes and the browser voice is used.
RUN python scripts/get_voice.py /app/models || (echo "Hindi voice not downloaded; the app will use the browser voice" && rm -rf /app/models/*)

# Run as a normal user; orders are stored in /data (mount a volume there)
RUN useradd --create-home appuser && mkdir -p /data && chown -R appuser /data /app
USER appuser

ENV DB_PATH=/data/orders.db \
    BKO_VOICE_MODEL=/app/models/hi_IN-pratham-medium.onnx \
    PORT=8000 \
    PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT','8000'), timeout=4)"

# Cloud hosts set $PORT; --proxy-headers keeps HTTPS links right behind their load balancer
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
