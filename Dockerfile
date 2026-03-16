# SwissUnihockey Stats - Docker Image
# Multi-stage build: builder installs deps into a venv, runtime copies it in.

# ---------------------------------------------------------------------------
# Stage 1: Builder — install Python dependencies into a clean virtualenv
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build tools, upgrade pip, create venv — all in one cached layer
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc-dev \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --upgrade pip --root-user-action=ignore \
    && python -m venv /app/venv \
    && /app/venv/bin/pip install --upgrade pip

# Copy requirements and install into the venv (cached unless requirements change)
COPY backend/requirements.txt .
RUN /app/venv/bin/pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2: Runtime — lean image, no build tools
# ---------------------------------------------------------------------------
FROM python:3.12-slim

LABEL maintainer="your.email@example.com"
LABEL description="SwissUnihockey Stats with intelligent caching"
LABEL version="1.0.0"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # venv is on PATH for all users — no --user / .local tricks needed
    PATH="/app/venv/bin:$PATH"

# Install gosu for privilege drop and curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends gosu curl \
    && rm -rf /var/lib/apt/lists/* \
    && gosu nobody true

# Non-root user
RUN useradd -m -u 1000 appuser

WORKDIR /app

# Copy venv from builder (owns nothing sensitive, safe for any user)
COPY --from=builder /app/venv /app/venv

# Copy application code
COPY --chown=appuser:appuser backend/app/       ./app/
COPY --chown=appuser:appuser backend/manage.py  ./
COPY --chown=appuser:appuser backend/locales/   ./locales/
COPY --chown=appuser:appuser backend/static/    ./static/
COPY --chown=appuser:appuser backend/templates/ ./templates/
COPY --chown=appuser:appuser scripts/           ./scripts/

# Entrypoint (runs as root → fixes /app/data ownership → drops to appuser)
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Data directory (entrypoint will chown at runtime so mounted volumes work too)
RUN mkdir -p /app/data/cache && chown -R appuser:appuser /app/data

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -fs http://127.0.0.1:8000/health || exit 1

EXPOSE 8000

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
