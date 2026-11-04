# syntax=docker/dockerfile:1
# ThermoMind — single image: Vite build of apps/web served by the FastAPI app.
#
#   docker build -t thermomind .
#   docker run --rm -p 8000:8000 -e MODEL_API_KEY=... -v "$PWD/data:/app/data" thermomind
#
# The image ships the CC BY 4.0 fixture (data/fixtures) only. The full UCI data set
# and the trained model live in the mounted data/ volume:
#   docker run --rm -v "$PWD/data:/app/data" thermomind python /app/scripts/fetch_uci.py
#   docker run --rm -v "$PWD/data:/app/data" thermomind python /app/scripts/train.py
# Never bake MODEL_API_KEY into the image; pass it with -e or docker-compose env_file.

# ---------- stage 1: web build ----------
FROM node:20-alpine AS web
WORKDIR /web
COPY apps/web/ ./
# npm ci removes any node_modules copied from the host and installs from the lockfile.
RUN npm ci && npm run build

# ---------- stage 2: python runtime ----------
FROM python:3.12-slim AS api
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    THERMOMIND_BUILD=docker-2026-11-04

WORKDIR /app

COPY apps/api/requirements.txt apps/api/requirements.txt
RUN pip install --no-cache-dir -r apps/api/requirements.txt

COPY apps/api apps/api
COPY scripts scripts
COPY data/fixtures data/fixtures
COPY data/README.md data/README.md
COPY --from=web /web/dist apps/web/dist

# Writable locations for the raw data set, the model and the SQLite DB (normally a volume).
RUN mkdir -p data/raw/uci_551 data/models

WORKDIR /app/apps/api
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
