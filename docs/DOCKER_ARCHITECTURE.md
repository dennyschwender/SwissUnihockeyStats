# 🐳 SwissUnihockey Docker Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Docker Environment                            │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                     Docker Compose Services                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌────────────────────┐  ┌───────────────────┐  ┌────────────────┐ │
│  │  swissunihockey    │  │  preload-cache    │  │ cache-refresher│ │
│  │  (main service)    │  │  (one-time run)   │  │  (optional)    │ │
│  │                    │  │                   │  │                │ │
│  │  • Python 3.11     │  │  • Populate cache │  │  • Hourly sync │ │
│  │  • API Client      │  │  • Exit after run │  │  • Background  │ │
│  │  • Interactive     │  │                   │  │                │ │
│  │  • Health checks   │  │                   │  │                │ │
│  └────────┬───────────┘  └─────────┬─────────┘  └────────┬───────┘ │
│           │                        │                      │         │
└───────────┼────────────────────────┼──────────────────────┼─────────┘
            │                        │                      │
            │                        │                      │
            ▼                        ▼                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Volume Mounts                                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Host: ./data/cache/  ◀──────▶  Container: /app/data/cache/        │
│  Host: ./scripts/     ─────▶     Container: /app/scripts/ (ro)     │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                     Network & External APIs                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Container: swissunihockey-client                                   │
│       │                                                              │
│       │  Outbound HTTPS                                             │
│       └─────────────▶  https://api-v2.swissunihockey.ch             │
│                                                                      │
│  Bridge Network: swissunihockey-net                                 │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                     Development Mode                                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Additional services (docker-compose.dev.yml):                      │
│                                                                      │
│  ┌──────────────────┐  ┌─────────────────┐                         │
│  │  jupyter         │  │  redis          │                          │
│  │  Port: 8888      │  │  Port: 6379     │                          │
│  │  Data exploration│  │  Optional cache │                          │
│  └──────────────────┘  └─────────────────┘                          │
│                                                                      │
│  Source code mounted for live reload                                │
│  Debug port 5678 exposed                                            │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                     CI/CD Pipeline                                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  GitHub Actions (.github/workflows/docker.yml):                     │
│                                                                      │
│  1. Code push to main/develop                                       │
│  2. Build Docker image                                              │
│  3. Run tests in container                                          │
│  4. Security scan (Trivy)                                           │
│  5. Push to GitHub Container Registry                               │
│                                                                      │
│  Registry: ghcr.io/YOUR_USERNAME/swissunihockey:latest              │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                     Resource Limits                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Production (default):                                              │
│  • CPU: 1.0 cores (reserved: 0.5)                                   │
│  • Memory: 512MB (reserved: 256MB)                                  │
│                                                                      │
│  Development (dev compose):                                         │
│  • CPU: 2.0 cores                                                    │
│  • Memory: 1GB                                                       │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                     Health Check                                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Interval: 30s                                                       │
│  Timeout: 10s                                                        │
│  Start period: 5s                                                    │
│  Retries: 3                                                          │
│                                                                      │
│  Command: python scripts/healthcheck.py                             │
│  ✓ Tests API client initialization                                  │
│  ✓ Verifies basic API connectivity                                  │
│  ✓ Auto-restart on failure                                          │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                     Image Build Process                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Stage 1: Builder                                                    │
│  ├─ FROM python:3.11-slim                                           │
│  ├─ Install build tools (gcc, libc-dev)                             │
│  ├─ Install Python dependencies                                     │
│  └─ Output: /root/.local with packages                              │
│                                                                      │
│  Stage 2: Runtime (final)                                           │
│  ├─ FROM python:3.11-slim                                           │
│  ├─ Copy dependencies from builder                                  │
│  ├─ Copy application code                                           │
│  ├─ Create non-root user (appuser)                                  │
│  ├─ Set permissions                                                 │
│  └─ CMD: Python interactive shell                                   │
│                                                                      │
│  Result: ~200MB optimized image                                     │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                     Quick Commands                                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Build:    make build                                               │
│  Start:    make up                                                   │
│  Preload:  make preload                                             │
│  Logs:     make logs                                                │
│  Shell:    make shell                                               │
│  Python:   make python                                              │
│  Dev:      make dev                                                  │
│  Test:     make test                                                 │
│  Clean:    make clean                                               │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## File Structure

```
swissunihockey/
├── Dockerfile                      # Multi-stage build definition
├── docker-compose.yml              # Main service orchestration
├── docker-compose.dev.yml          # Development overrides
├── .dockerignore                   # Build context exclusions
├── Makefile                        # Common commands
├── docker-quickstart.sh            # Linux/Mac setup script
├── docker-quickstart.ps1           # Windows setup script
├── .env.docker.example             # Environment variables template
│
├── .github/workflows/
│   └── docker.yml                  # CI/CD pipeline
│
├── scripts/
│   └── healthcheck.py              # Container health verification
│
├── data/
│   └── cache/                      # Persistent cache volume
│       └── .gitkeep
│
└── DOCKER.md                       # Complete documentation
```

## Data Flow

```
User Request
    │
    ▼
┌─────────────────┐
│ Make Command    │  ─▶  make build, make up, make preload
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Docker Compose  │  ─▶  Orchestrates containers
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Container       │  ─▶  Runs Python + API client
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ API Client      │  ─▶  CacheManager checks cache
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
Cache Hit   Cache Miss
    │         │
    │         ▼
    │    ┌─────────────────┐
    │    │ HTTP Request    │  ─▶  api-v2.swissunihockey.ch
    │    └────────┬────────┘
    │             │
    │             ▼
    │    ┌─────────────────┐
    │    │ Save to Cache   │  ─▶  data/cache/{category}/{hash}.json
    │    └────────┬────────┘
    │             │
    └─────────────┘
         │
         ▼
┌─────────────────┐
│ Return Data     │  ─▶  Back to user/application
└─────────────────┘
```

## Deployment Scenarios

### Development

```bash
make dev-jupyter
# ✓ Source code mounted (live reload)
# ✓ Jupyter Lab on port 8888
# ✓ Redis available (optional)
# ✓ Debug port 5678 exposed
```

### Testing

```bash
make build
make test
# ✓ Run pytest in container
# ✓ Isolated environment
# ✓ Same as CI/CD
```

### Production

```bash
# Single server
docker run -d --name swissunihockey \
  -v $(pwd)/data/cache:/app/data/cache \
  --restart unless-stopped \
  swissunihockey:prod

# Kubernetes
kubectl apply -f k8s/

# Docker Swarm
docker stack deploy -c docker-compose.yml swissunihockey
```

## Advantages

✅ **Consistency** - Same environment everywhere (dev, test, prod)  
✅ **Isolation** - No dependency conflicts with host system  
✅ **Portability** - Run on any OS with Docker  
✅ **Security** - Non-root user, minimal attack surface  
✅ **Efficiency** - Multi-stage build, layer caching  
✅ **Automation** - CI/CD pipeline, health checks  
✅ **Scalability** - Easy to scale horizontally  
✅ **Simplicity** - One-command setup and deployment  

---

**More details**: See [DOCKER.md](./DOCKER.md) for complete documentation
