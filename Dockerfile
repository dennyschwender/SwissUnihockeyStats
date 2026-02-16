# SwissUnihockey API Client - Docker Image
# Multi-stage build for optimized image size

# Stage 1: Builder
FROM python:3.11-slim as builder

# Set working directory
WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim

# Set maintainer label
LABEL maintainer="your.email@example.com"
LABEL description="SwissUnihockey API Client with intelligent caching"
LABEL version="1.0.0"

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/data/cache && \
    chown -R appuser:appuser /app

# Set working directory
WORKDIR /app

# Copy Python dependencies from builder
COPY --from=builder /root/.local /home/appuser/.local

# Copy application code
COPY --chown=appuser:appuser api/ ./api/
COPY --chown=appuser:appuser scripts/ ./scripts/
COPY --chown=appuser:appuser config.ini ./
COPY --chown=appuser:appuser .env.example ./

# Create cache directory with proper permissions
RUN mkdir -p /app/data/cache && \
    chown -R appuser:appuser /app/data

# Switch to non-root user
USER appuser

# Update PATH
ENV PATH=/home/appuser/.local/bin:$PATH

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "from api import SwissUnihockeyClient; client = SwissUnihockeyClient(); client.get_clubs()" || exit 1

# Default command: Python shell with API client available
CMD ["python", "-i", "-c", "from api import SwissUnihockeyClient; client = SwissUnihockeyClient(); print('SwissUnihockey API Client ready! Use: client.get_clubs(), client.get_leagues(), etc.')"]
