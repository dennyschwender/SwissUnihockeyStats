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

# Copy requirements from backend directory
COPY backend/requirements.txt .

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

# Copy application code from backend directory
COPY --chown=appuser:appuser backend/app/ ./app/
COPY --chown=appuser:appuser backend/manage.py ./
COPY --chown=appuser:appuser backend/.env.example ./
COPY --chown=appuser:appuser backend/locales/ ./locales/
COPY --chown=appuser:appuser backend/static/ ./static/
COPY --chown=appuser:appuser backend/templates/ ./templates/
COPY --chown=appuser:appuser scripts/ ./scripts/

# Create cache directory with proper permissions
RUN mkdir -p /app/data/cache && \
    chown -R appuser:appuser /app/data

# Switch to non-root user
USER appuser

# Update PATH
ENV PATH=/home/appuser/.local/bin:$PATH

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health', timeout=5)" || exit 1

# Expose port
EXPOSE 8000

# Default command: Run FastAPI server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
