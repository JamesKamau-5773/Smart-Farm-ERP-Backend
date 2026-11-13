# Maziwa Smart backend: Flask API (gunicorn) and Celery worker share this image.
# Build:  docker build -t maziwa-backend .
# Web:    docker run --env-file .env -p 10000:10000 maziwa-backend
# Worker: docker run --env-file .env maziwa-backend celery -A celery_worker.celery worker --loglevel=info

# Matches the local venv. The app talks to PostgreSQL through psycopg v3 only.
ARG PYTHON_VERSION=3.13

# --- Build stage: compile wheels so the runtime image needs no compilers ---
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt


# --- Runtime stage ---
FROM python:${PYTHON_VERSION}-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=10000 \
    UPLOAD_ROOT=/app/instance/uploads \
    XDG_CACHE_HOME=/tmp/.cache

# WeasyPrint (receipt PDFs) needs Pango/HarfBuzz and real fonts; libpq for PostgreSQL.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libharfbuzz-subset0 \
        libfontconfig1 \
        fonts-dejavu-core \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system app && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels /wheels/* && rm -rf /wheels

COPY --chown=app:app . .
RUN mkdir -p "$UPLOAD_ROOT" && chown -R app:app /app/instance && chmod +x scripts/start_web.sh

USER app

EXPOSE 10000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"10000\")}/health', timeout=4)" || exit 1

# Runs migrations, then gunicorn (see scripts/start_web.sh).
CMD ["./scripts/start_web.sh"]
