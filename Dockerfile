# Stage 1: Builder
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml pyproject.toml
COPY README.md README.md
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .[api,gsc,seo]

# Stage 2: Runtime
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY . .

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT:-8000}/api/v1/health" || exit 1

ENV ENVIRONMENT=production
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# The API runs crawls in-process. No Celery worker: its `execute_crawl` task is
# a stub that marks a job succeeded without crawling, so running it alongside
# the API would overwrite real results. `server.py` exposes a factory, not an
# `app` attribute, hence `--factory`. `exec` makes uvicorn PID 1, so a crash
# stops the container and the platform restarts it.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn --factory src.api.server:create_app --host 0.0.0.0 --port ${PORT:-8000}"]
