# Deployment Guide

This guide will help you deploy SwissUnihockeyStats to production.

## Table of Contents
- [Prerequisites](#prerequisites)
- [Environment Variables](#environment-variables)
- [Deployment Options](#deployment-options)
- [Health Monitoring](#health-monitoring)
- [Troubleshooting](#troubleshooting)

## Prerequisites

- Python 3.11 or higher
- Git
- A hosting platform account (Render, Railway, DigitalOcean, etc.)

## Environment Variables

Create a `.env` file or configure these in your hosting platform:

```bash
# Application Settings
APP_ENV=production
DEBUG=false
SECRET_KEY=your-secret-key-here-generate-with-openssl-rand-hex-32

# API Configuration
SWISSUNIHOCKEY_API_URL=https://api-v2.swissunihockey.ch
SWISSUNIHOCKEY_LOCALE=de
SWISSUNIHOCKEY_CACHE_ENABLED=true
SWISSUNIHOCKEY_CACHE_DIR=./data/cache

# Server Configuration (optional)
HOST=0.0.0.0
PORT=8000
WORKERS=4

# Logging
LOG_LEVEL=INFO
```

### Generating a Secret Key

```bash
# On Linux/Mac
openssl rand -hex 32

# On Windows (PowerShell)
[Convert]::ToBase64String([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32))

# Using Python
python -c "import secrets; print(secrets.token_hex(32))"
```

## Deployment Options

### Option 1: Render.com (Recommended)

**Why Render?** Free tier available, automatic SSL, easy deploys from Git.

1. **Create a new Web Service**
   - Connect your GitHub repository
   - Select branch: `main`
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT`

2. **Configure Environment Variables**
   - Add all variables from the `.env` section above
   - Set `APP_ENV=production`
   - Generate and set a unique `SECRET_KEY`

3. **Auto-Deploy**
   - Enable auto-deploy from main branch
   - Render will automatically rebuild on every push

**Resource Requirements:**
- Free tier: Works for demo/testing
- Starter ($7/month): Recommended for production
- Standard ($25/month): For higher traffic

### Option 2: Railway.app

**Why Railway?** Modern platform, $5 free credit monthly, simple setup.

1. **Create New Project**
   ```bash
   railway login
   railway init
   railway link
   ```

2. **Configure Build**
   ```bash
   railway up
   ```

3. **Add Environment Variables**
   ```bash
   railway variables set APP_ENV=production
   railway variables set SECRET_KEY=your-secret-key-here
   # Add other variables...
   ```

4. **Deploy**
   ```bash
   railway up
   ```

**Railway Configuration (railway.json):**
```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "NIXPACKS"
  },
  "deploy": {
    "startCommand": "uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT",
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10
  }
}
```

### Option 3: DigitalOcean App Platform

**Why DigitalOcean?** Reliable, scalable, good for growing apps.

1. **Create App**
   - Choose GitHub as source
   - Select repository and branch

2. **Configure Build**
   - Build Command: `pip install -r requirements.txt`
   - Run Command: `gunicorn backend.app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8080`

3. **Set Environment Variables** in the App Platform dashboard

4. **Configure Resources**
   - Basic: $5/month (512 MB RAM, 1 vCPU)
   - Professional: $12/month (1 GB RAM, 1 vCPU)

### Option 4: Docker (Self-Hosted)

**For VPS or on-premise deployment**

1. **Build Docker Image**
   ```bash
   docker build -t swissunihockey-stats .
   ```

2. **Run Container**
   ```bash
   docker run -d \
     -p 8000:8000 \
     -e APP_ENV=production \
     -e SECRET_KEY=your-secret-key \
     --name swissunihockey-stats \
     swissunihockey-stats
   ```

3. **Using Docker Compose**
   ```bash
   # Create docker-compose.prod.yml
   docker-compose -f docker-compose.prod.yml up -d
   ```

**Sample Production docker-compose.prod.yml:**
```yaml
version: '3.8'

services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - APP_ENV=production
      - SECRET_KEY=${SECRET_KEY}
      - SWISSUNIHOCKEY_API_URL=https://api-v2.swissunihockey.ch
      - SWISSUNIHOCKEY_CACHE_ENABLED=true
    volumes:
      - ./data:/app/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

### Option 5: Traditional VPS (Ubuntu/Debian)

1. **Install Dependencies**
   ```bash
   sudo apt update
   sudo apt install python3.11 python3-pip nginx certbot python3-certbot-nginx
   ```

2. **Clone and Setup**
   ```bash
   cd /var/www
   git clone https://github.com/yourusername/SwissUnihockeyStats.git
   cd SwissUnihockeyStats
   python3.11 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Create Systemd Service**
   ```bash
   sudo nano /etc/systemd/system/swissunihockey.service
   ```

   ```ini
   [Unit]
   Description=SwissUnihockey Stats
   After=network.target

   [Service]
   Type=notify
   User=www-data
   Group=www-data
   WorkingDirectory=/var/www/SwissUnihockeyStats
   Environment="PATH=/var/www/SwissUnihockeyStats/venv/bin"
   ExecStart=/var/www/SwissUnihockeyStats/venv/bin/gunicorn backend.app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 127.0.0.1:8000
   ExecReload=/bin/kill -s HUP $MAINPID
   KillMode=mixed
   TimeoutStopSec=5
   PrivateTmp=true

   [Install]
   WantedBy=multi-user.target
   ```

4. **Configure Nginx**
   ```bash
   sudo nano /etc/nginx/sites-available/swissunihockey
   ```

   ```nginx
   server {
       listen 80;
       server_name your-domain.com;

       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
   }
   ```

5. **Enable and Start**
   ```bash
   sudo ln -s /etc/nginx/sites-available/swissunihockey /etc/nginx/sites-enabled/
   sudo systemctl enable swissunihockey
   sudo systemctl start swissunihockey
   sudo systemctl reload nginx
   
   # Setup SSL
   sudo certbot --nginx -d your-domain.com
   ```

## Health Monitoring

### Built-in Health Check

The application includes a health check endpoint at `/health`:

```bash
curl https://your-domain.com/health
```

Expected response:
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00Z",
  "version": "1.0.0"
}
```

### Monitoring Services

**UptimeRobot** (Free, Simple)
1. Sign up at uptimerobot.com
2. Add new monitor: HTTP(s)
3. URL: `https://your-domain.com/health`
4. Check interval: 5 minutes

**Better Uptime** (Free tier, Prettier)
1. Sign up at betteruptime.com
2. Create new monitor
3. Configure alerts (email, Slack, etc.)

### Application Monitoring

Add these tools for deeper insights:

**Sentry (Error Tracking)**
```bash
pip install sentry-sdk[fastapi]
```

```python
# Add to backend/app/main.py
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration

sentry_sdk.init(
    dsn="your-sentry-dsn",
    integrations=[FastApiIntegration()],
    traces_sample_rate=1.0,
    environment=settings.APP_ENV
)
```

**Prometheus + Grafana** (For advanced metrics)
```bash
pip install prometheus-fastapi-instrumentator
```

## Performance Optimization

### 1. Enable Caching

Ensure caching is enabled in production:
```bash
SWISSUNIHOCKEY_CACHE_ENABLED=true
SWISSUNIHOCKEY_CACHE_DIR=/app/data/cache
```

### 2. Configure Workers

Calculate optimal workers:
```
workers = (2 × CPU cores) + 1
```

For a 2-core machine:
```bash
gunicorn backend.app.main:app -w 5 -k uvicorn.workers.UvicornWorker
```

### 3. Enable Gzip Compression

Add to main.py:
```python
from fastapi.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=1000)
```

### 4. CDN for Static Assets

Use Cloudflare or similar for:
- htmx.js
- alpine.js
- Chart.js

## Security Checklist

- [ ] Set strong `SECRET_KEY` (32+ characters)
- [ ] Set `DEBUG=false` in production
- [ ] Enable HTTPS (SSL certificate)
- [ ] Configure CORS properly
- [ ] Keep dependencies updated (`pip list --outdated`)
- [ ] Set up automated backups
- [ ] Configure rate limiting
- [ ] Enable security headers

## Backup Strategy

### Cache Directory
```bash
# Backup cache (can be regenerated if lost)
tar -czf cache-backup-$(date +%Y%m%d).tar.gz data/cache
```

### Configuration
```bash
# Backup environment variables (store securely!)
cp .env .env.backup
```

## Troubleshooting

### Application Won't Start

1. Check logs:
   ```bash
   # Docker
   docker logs swissunihockey-stats
   
   # Systemd
   sudo journalctl -u swissunihockey -n 50
   
   # Render/Railway
   Check dashboard logs
   ```

2. Verify environment variables:
   ```bash
   env | grep SWISSUNIHOCKEY
   ```

3. Test locally:
   ```bash
   uvicorn backend.app.main:app --reload
   ```

### Slow Response Times

1. Check cache status:
   ```bash
   ls -lh data/cache/
   ```

2. Monitor API calls:
   - Check `/health` endpoint
   - Look for rate limiting from Swiss Unihockey API

3. Increase workers:
   ```bash
   gunicorn backend.app.main:app -w 8 -k uvicorn.workers.UvicornWorker
   ```

### Memory Issues

1. Limit cache size in `backend/app/config.py`
2. Reduce number of workers
3. Upgrade hosting plan (more RAM)

### API Rate Limiting

Swiss Unihockey API has rate limits:
- Enable caching: `SWISSUNIHOCKEY_CACHE_ENABLED=true`
- Cache stores data for 30 days
- Reduces API calls by 99%

## Updating the Application

### Render/Railway (Auto-deploy)
```bash
git push origin main
# Automatically deploys
```

### Docker
```bash
git pull
docker-compose down
docker-compose build
docker-compose up -d
```

### VPS
```bash
cd /var/www/SwissUnihockeyStats
git pull
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart swissunihockey
```

## Support

- GitHub Issues: [Report bugs or request features]
- Documentation: See README.md
- API Status: Check Swiss Unihockey API uptime

## Cost Estimates

| Platform | Free Tier | Paid Plans | Best For |
|----------|-----------|------------|----------|
| Render | Yes (limited) | $7-25/mo | Side projects, MVPs |
| Railway | $5 credit/mo | Pay-as-you-go | Development, testing |
| DigitalOcean | No | $5-12/mo | Production apps |
| Heroku | No (ended) | $7+/mo | Legacy migrations |
| Self-hosted VPS | N/A | $5-20/mo | Full control |

**Recommended:** Start with Render free tier for testing, upgrade to Starter ($7/mo) for production.

---

**Last Updated:** January 2026  
**Maintainers:** See CONTRIBUTING.md
