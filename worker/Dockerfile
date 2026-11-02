# Media Worker: no HTTP, only the queue (System_Architecture.md §3).
# Debian 12 ships FFmpeg 5.1 with libmp3lame — NFR-17 requires FFmpeg 5.0+.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg espeak-ng \
    && rm -rf /var/lib/apt/lists/*

# The platform voice tag "OhBeat" (FR-10), synthesized at build time (ASSUMPTION: GAP-45).
# Replace /opt/ohbeat/voice_tag.wav with a real recording if you have one.
RUN mkdir -p /opt/ohbeat \
    && espeak-ng -v en -s 120 -p 40 -w /tmp/tag_raw.wav "Oh Beat" \
    && ffmpeg -loglevel error -i /tmp/tag_raw.wav -ar 44100 -ac 2 -af "loudnorm=I=-14" /opt/ohbeat/voice_tag.wav \
    && rm /tmp/tag_raw.wav

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY . .

CMD ["python", "-m", "worker.main"]
