# 🐳 Docker Deployment Guide

Complete guide for running SwissUnihockey API Client with Docker and Docker Compose.

---

## 📋 Table of Contents

- [Quick Start](#quick-start)
- [Prerequisites](#prerequisites)
- [Basic Usage](#basic-usage)
- [Docker Compose Services](#docker-compose-services)
- [Configuration](#configuration)
- [Development](#development)
- [Production Deployment](#production-deployment)
- [Makefile Commands](#makefile-commands)
- [Troubleshooting](#troubleshooting)

---

## 🚀 Quick Start

### 1. Build and Run

```bash
# Build the Docker image
docker-compose build

# Start the container
docker-compose up -d

# Preload cache (recommended)
docker-compose run --rm preload-cache

# Check logs
docker-compose logs -f
```

### 2. Using Makefile (even easier!)

```bash
# Build
make build

# Start
make up

# Preload cache
make preload

# View logs
make logs
```

---

## 📦 Prerequisites

- Docker 20.10+
- Docker Compose 2.0+
- 512MB RAM minimum
- 1GB disk space for cache

**Installation**:
- Docker Desktop: https://www.docker.com/products/docker-desktop
- Docker Engine (Linux): https://docs.docker.com/engine/install/

---

## 💻 Basic Usage

### Using Docker Compose

```bash
# Start container
docker-compose up -d

# Open Python shell in container
docker-compose exec swissunihockey python

# Run preload script
docker-compose run --rm preload-cache

# View cache statistics
docker-compose exec swissunihockey python -c \
  "from api import SwissUnihockeyClient; \
   c = SwissUnihockeyClient(); \
   print(c.cache.get_stats())"

# Stop container
docker-compose down
```

### Using Python in Container

```bash
# Interactive Python shell
docker-compose exec swissunihockey python

>>> from api import SwissUnihockeyClient
>>> client = SwissUnihockeyClient()
>>> clubs = client.get_clubs()
>>> print(f"Found {len(clubs['entries'])} clubs")
```

### Running Scripts

```bash
# Run any script in the container
docker-compose exec swissunihockey python scripts/example_fetch_data.py

# Run preload cache
docker-compose exec swissunihockey python scripts/preload_cache.py

# Run custom script
docker-compose exec swissunihockey python -c "
from api import SwissUnihockeyClient
client = SwissUnihockeyClient()
leagues = client.get_leagues()
print(f'Leagues: {len(leagues[\"entries\"])}')
"
```

---

## 🛠️ Docker Compose Services

### 1. Main Service: `swissunihockey`

**Purpose**: Main API client container  
**Status**: Always running  
**Access**: `docker-compose exec swissunihockey python`

```bash
# Start
docker-compose up -d swissunihockey

# Access Python shell
docker-compose exec swissunihockey python

# View logs
docker-compose logs -f swissunihockey
```

### 2. Cache Preloader: `preload-cache`

**Purpose**: One-time cache population  
**Status**: Runs once and exits  
**Profile**: `preload`

```bash
# Run preloader
docker-compose run --rm preload-cache

# Or with profile
docker-compose --profile preload up preload-cache
```

### 3. Auto Refresher: `cache-refresher`

**Purpose**: Hourly cache refresh  
**Status**: Optional, runs in background  
**Profile**: `auto-refresh`

```bash
# Start auto-refresh
docker-compose --profile auto-refresh up -d cache-refresher

# Stop auto-refresh
docker-compose stop cache-refresher
```

---

## ⚙️ Configuration

### Environment Variables

Set in `docker-compose.yml` or `.env` file:

```bash
# .env file
SWISSUNIHOCKEY_API_URL=https://api-v2.swissunihockey.ch
SWISSUNIHOCKEY_LOCALE=de-CH
SWISSUNIHOCKEY_CACHE_ENABLED=true
SWISSUNIHOCKEY_CACHE_DIR=/app/data/cache
TZ=Europe/Zurich
```

### Volume Mounts

**Cache persistence**:
```yaml
volumes:
  - ./data/cache:/app/data/cache  # Cache persists on host
```

**Script access** (read-only):
```yaml
volumes:
  - ./scripts:/app/scripts:ro
```

### Resource Limits

Configured in `docker-compose.yml`:
```yaml
deploy:
  resources:
    limits:
      cpus: '1.0'
      memory: 512M
    reservations:
      cpus: '0.5'
      memory: 256M
```

---

## 🛠️ Development

### Development Mode

Use `docker-compose.dev.yml` for development with live code reloading:

```bash
# Start development environment
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d

# Or with Make
make dev
```

**Features**:
- ✅ Source code mounted (live reload)
- ✅ Debug port exposed (5678)
- ✅ Increased resource limits
- ✅ Development tools included

### Jupyter Lab

For data exploration:

```bash
# Start with Jupyter
docker-compose -f docker-compose.yml -f docker-compose.dev.yml --profile jupyter up -d

# Or with Make
make dev-jupyter

# Access at: http://localhost:8888
```

### Interactive Development

```bash
# Open bash shell in container
docker-compose exec swissunihockey bash

# Install additional packages
docker-compose exec swissunihockey pip install package-name

# Run tests
docker-compose exec swissunihockey pytest tests/
```

---

## 🚀 Production Deployment

### Build Production Image

```bash
# Build optimized production image
docker build -t swissunihockey:prod .

# Run production container
docker run -d \
  --name swissunihockey-prod \
  -v $(pwd)/data/cache:/app/data/cache \
  -e SWISSUNIHOCKEY_CACHE_ENABLED=true \
  --restart unless-stopped \
  swissunihockey:prod
```

### Docker Swarm

```bash
# Initialize swarm (if not already done)
docker swarm init

# Deploy stack
docker stack deploy -c docker-compose.yml swissunihockey

# Scale service
docker service scale swissunihockey_swissunihockey=3

# Remove stack
docker stack rm swissunihockey
```

### Kubernetes

```bash
# Generate Kubernetes manifests
kompose convert -f docker-compose.yml

# Deploy to Kubernetes
kubectl apply -f swissunihockey-deployment.yaml
kubectl apply -f swissunihockey-service.yaml
```

### Health Checks

Container includes health check:

```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "from api import SwissUnihockeyClient; ..."
```

Check status:
```bash
docker inspect swissunihockey-client | grep -A 5 Health
```

---

## 🎯 Makefile Commands

### Most Used Commands

```bash
make help          # Show all available commands
make build         # Build Docker images
make up            # Start containers
make down          # Stop containers
make restart       # Restart containers
make logs          # Show logs
make shell         # Open shell in container
make python        # Open Python shell
make preload       # Preload cache
make cache-stats   # Show cache statistics
make clean         # Clean up containers/volumes
```

### Development Commands

```bash
make dev           # Start dev environment
make dev-jupyter   # Start with Jupyter
make test          # Run tests in container
```

### Utility Commands

```bash
make stats         # Show resource usage
make inspect       # Inspect container
make cache-clear   # Clear all cache
make version       # Show Docker versions
```

---

## 🔧 Troubleshooting

### Container Won't Start

```bash
# Check logs
docker-compose logs swissunihockey

# Inspect container
docker inspect swissunihockey-client

# Check resource usage
docker stats swissunihockey-client
```

### Cache Not Persisting

```bash
# Verify volume mount
docker-compose config | grep volumes -A 5

# Check permissions
docker-compose exec swissunihockey ls -la /app/data/cache

# Manually create directory
mkdir -p ./data/cache
```

### API Requests Failing

```bash
# Test connection from container
docker-compose exec swissunihockey python -c "
from api import SwissUnihockeyClient
client = SwissUnihockeyClient(use_cache=False)
try:
    clubs = client.get_clubs()
    print('Connection OK')
except Exception as e:
    print(f'Error: {e}')
"

# Check DNS resolution
docker-compose exec swissunihockey ping -c 3 api-v2.swissunihockey.ch
```

### Out of Memory

```bash
# Increase memory limit in docker-compose.yml
deploy:
  resources:
    limits:
      memory: 1G  # Increase from 512M

# Or restart Docker Desktop with more resources
```

### Permission Denied

```bash
# Fix ownership
sudo chown -R $USER:$USER ./data/cache

# Or run as root (not recommended)
docker-compose exec -u root swissunihockey bash
```

### Clean Slate

```bash
# Remove everything and start fresh
make clean-all
make build
make up
make preload
```

---

## 📊 Monitoring

### Resource Usage

```bash
# Real-time stats
docker stats swissunihockey-client

# Or with Make
make stats
```

### Cache Statistics

```bash
# Via Make
make cache-stats

# Manual
docker-compose exec swissunihockey python -c "
from api import SwissUnihockeyClient
import json
c = SwissUnihockeyClient()
print(json.dumps(c.cache.get_stats(), indent=2))
"
```

### Logs

```bash
# Follow logs
docker-compose logs -f

# Last 100 lines
docker-compose logs --tail=100

# Specific service
docker-compose logs -f swissunihockey
```

---

## 🔐 Security

### Best Practices

1. **Run as non-root user** (already configured)
2. **Use read-only mounts** for scripts
3. **Set resource limits** to prevent DoS
4. **Use secrets for sensitive data**
5. **Regular image updates**

### Docker Secrets

For production with sensitive data:

```yaml
services:
  swissunihockey:
    secrets:
      - api_token
    environment:
      - API_TOKEN_FILE=/run/secrets/api_token

secrets:
  api_token:
    file: ./secrets/api_token.txt
```

---

## 🚀 CI/CD Integration

### GitHub Actions

```yaml
# .github/workflows/docker.yml
name: Docker Build

on:
  push:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Build Docker image
        run: docker-compose build
      - name: Run tests
        run: docker-compose run --rm swissunihockey pytest
```

### GitLab CI

```yaml
# .gitlab-ci.yml
docker-build:
  image: docker:latest
  services:
    - docker:dind
  script:
    - docker-compose build
    - docker-compose run --rm swissunihockey pytest tests/
```

---

## 📚 Additional Resources

- **Docker Documentation**: https://docs.docker.com
- **Docker Compose**: https://docs.docker.com/compose/
- **Best Practices**: https://docs.docker.com/develop/dev-best-practices/
- **Security**: https://docs.docker.com/engine/security/

---

## 🎉 Summary

✅ **Built**: Optimized multi-stage Docker image  
✅ **Configured**: Production-ready docker-compose.yml  
✅ **Automated**: Makefile for common operations  
✅ **Cached**: Persistent volume for cache storage  
✅ **Monitored**: Health checks and resource limits  
✅ **Secured**: Non-root user and best practices  

**Start using Docker now**:
```bash
make build && make up && make preload
```

**Your SwissUnihockey client is now fully containerized! 🐳🚀**
