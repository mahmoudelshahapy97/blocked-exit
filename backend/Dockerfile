FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    YOLO_CONFIG_DIR=/tmp/ultralytics

# OpenCV and RTSP decoding need these; ffmpeg also lets us test with local files.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        ffmpeg \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Torch build: CPU-only by default (~3GB image; CUDA makes it ~12GB). For a GPU,
# build with --build-arg TORCH_INDEX_URL=https://download.pytorch.org/whl/cu126
# and run with DEVICE=cuda; the root docker-compose.yml does both.
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
        --extra-index-url ${TORCH_INDEX_URL}

COPY app ./app
COPY alembic.ini .
COPY alembic ./alembic
COPY scripts ./scripts

RUN chmod +x /app/scripts/entrypoint.sh \
    && mkdir -p /app/models /app/data/snapshots \
    && useradd --create-home --uid 1000 insighteye \
    && chown -R insighteye:insighteye /app
USER insighteye

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/v1/health || exit 1

# Migrations run in the entrypoint so a failed upgrade stops the container
# rather than leaving an API serving against an unknown schema.
ENTRYPOINT ["/app/scripts/entrypoint.sh"]

# One process, always. Stream workers are in-process threads holding per-camera
# tracker state; a second uvicorn worker would open every RTSP stream twice and
# write duplicate events. Scale by adding cameras, not processes.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--timeout-graceful-shutdown", "30"]
