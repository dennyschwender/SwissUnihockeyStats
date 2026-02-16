# 🖥️ Tech Stack Decision Matrix - SwissUnihockey 2026

## Frontend Framework Comparison

| Criteria | Next.js (React) | Nuxt (Vue.js) | SvelteKit | Rating |
|----------|----------------|---------------|-----------|---------|
| **Performance** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | SvelteKit wins |
| **Mobile-First** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | Next.js best |
| **PWA Support** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | Tie |
| **Learning Curve** | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | Nuxt easiest |
| **Community** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | Next.js largest |
| **Job Market** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | Next.js best |
| **UI Libraries** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | Next.js most |
| **Real-time** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | Next.js best |
| **SEO** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | Tie |
| **Deployment** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | Next.js easiest |

**🏆 RECOMMENDATION: Next.js with React**

**Why?**
- Best mobile-first experience
- Largest ecosystem (shadcn/ui, Radix UI)
- Vercel deployment (zero config)
- Excellent real-time support
- Most job opportunities
- Great TypeScript support

---

## Detailed Technology Stack

### Frontend Stack (Chosen: Next.js)

```json
{
  "framework": "Next.js 15+",
  "language": "TypeScript",
  "styling": {
    "framework": "TailwindCSS",
    "components": "shadcn/ui",
    "icons": "Lucide React",
    "animations": "Framer Motion"
  },
  "state": {
    "client": "Zustand",
    "server": "@tanstack/react-query"
  },
  "forms": "React Hook Form + Zod",
  "charts": "Recharts",
  "pwa": "next-pwa",
  "realtime": "Socket.IO Client"
}
```

### Backend Stack

```json
{
  "framework": "FastAPI",
  "language": "Python 3.11+",
  "orm": "SQLAlchemy 2.0",
  "migration": "Alembic",
  "validation": "Pydantic V2",
  "async": "asyncio + aiohttp",
  "websockets": "FastAPI WebSockets",
  "auth": "FastAPI-Users",
  "testing": "pytest + pytest-asyncio"
}
```

### Database & Caching

```json
{
  "primary_db": "PostgreSQL 16",
  "cache": "Redis 7",
  "search": "PostgreSQL Full-Text Search",
  "connection_pool": "asyncpg"
}
```

### Deployment & Infrastructure

```json
{
  "frontend_host": "Vercel",
  "backend_host": "Railway.app",
  "database": "Supabase PostgreSQL",
  "cache": "Upstash Redis",
  "cdn": "Cloudflare",
  "storage": "Cloudflare R2",
  "monitoring": "Sentry",
  "analytics": "Plausible Analytics"
}
```

---

## File Structure

### Frontend (Next.js App Directory)

```
swiss-unihockey-web/
├── app/
│   ├── layout.tsx              # Root layout
│   ├── page.tsx                # Home page (league dashboard)
│   ├── leagues/
│   │   └── [id]/page.tsx       # League standings
│   ├── teams/
│   │   └── [id]/page.tsx       # Team profile
│   ├── players/
│   │   └── [id]/page.tsx       # Player profile
│   ├── games/
│   │   ├── page.tsx            # All games
│   │   ├── live/page.tsx       # Live games
│   │   └── [id]/page.tsx       # Match details
│   └── api/
│       └── [...]/route.ts      # API routes
├── components/
│   ├── ui/                     # shadcn/ui components
│   ├── leagues/
│   │   ├── LeagueTable.tsx
│   │   └── StandingsCard.tsx
│   ├── players/
│   │   ├── PlayerCard.tsx
│   │   ├── PlayerStats.tsx
│   │   └── TopScorers.tsx
│   ├── games/
│   │   ├── LiveScoreCard.tsx
│   │   ├── MatchTimeline.tsx
│   │   └── GameSchedule.tsx
│   └── shared/
│       ├── Header.tsx
│       ├── Navigation.tsx
│       ├── SearchBar.tsx
│       └── ThemeToggle.tsx
├── lib/
│   ├── api/
│   │   ├── client.ts           # API client wrapper
│   │   ├── queries.ts          # React Query hooks
│   │   └── types.ts            # TypeScript types
│   ├── utils/
│   │   ├── formatters.ts       # Date, number formatting
│   │   ├── helpers.ts          # Utility functions
│   │   └── constants.ts        # App constants
│   └── hooks/
│       ├── useLiveScores.ts
│       ├── useFavorites.ts
│       └── useNotifications.ts
├── public/
│   ├── icons/                  # PWA icons
│   ├── images/
│   └── manifest.json           # PWA manifest
├── styles/
│   └── globals.css             # Global styles
├── next.config.js
├── tailwind.config.js
└── package.json
```

### Backend (FastAPI)

```
swiss-unihockey-api/
├── app/
│   ├── main.py                 # FastAPI application
│   ├── config.py               # Configuration
│   ├── database.py             # Database connection
│   ├── models/
│   │   ├── club.py
│   │   ├── team.py
│   │   ├── player.py
│   │   ├── game.py
│   │   └── user.py
│   ├── schemas/
│   │   ├── club.py             # Pydantic schemas
│   │   ├── team.py
│   │   ├── player.py
│   │   └── game.py
│   ├── api/
│   │   ├── v1/
│   │   │   ├── clubs.py
│   │   │   ├── teams.py
│   │   │   ├── players.py
│   │   │   ├── games.py
│   │   │   ├── live.py         # Live scores WebSocket
│   │   │   └── search.py
│   │   └── deps.py             # Dependencies
│   ├── services/
│   │   ├── swissunihockey.py   # API client integration
│   │   ├── cache.py            # Redis caching
│   │   └── notifications.py    # Push notifications
│   ├── tasks/
│   │   ├── sync_data.py        # Celery tasks
│   │   └── update_live.py      # Live score updates
│   └── utils/
│       ├── security.py
│       └── helpers.py
├── migrations/                 # Alembic migrations
├── tests/
├── requirements.txt
└── Dockerfile
```

---

## Development Commands

### Frontend

```bash
# Install dependencies
npm install

# Development server (http://localhost:3000)
npm run dev

# Build for production
npm run build

# Start production server
npm start

# Linting
npm run lint

# Type checking
npm run type-check

# Run tests
npm run test
```

### Backend

```bash
# Install dependencies
pip install -r requirements.txt

# Development server (http://localhost:8000)
uvicorn app.main:app --reload

# Run migrations
alembic upgrade head

# Create migration
alembic revision --autogenerate -m "description"

# Run tests
pytest

# Run with Docker
docker-compose up
```

---

## Environment Variables

### Frontend (.env.local)

```bash
# API
NEXT_PUBLIC_API_URL=https://api.swissunihockey.app
NEXT_PUBLIC_WS_URL=wss://api.swissunihockey.app/ws

# Analytics
NEXT_PUBLIC_PLAUSIBLE_DOMAIN=swissunihockey.app

# Features
NEXT_PUBLIC_ENABLE_PWA=true
NEXT_PUBLIC_ENABLE_NOTIFICATIONS=true

# Sentry (optional)
NEXT_PUBLIC_SENTRY_DSN=
```

### Backend (.env)

```bash
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/swissunihockey

# Redis
REDIS_URL=redis://localhost:6379

# SwissUnihockey API
SWISSUNIHOCKEY_API_URL=https://api-v2.swissunihockey.ch
SWISSUNIHOCKEY_LOCALE=de-CH

# Security
SECRET_KEY=your-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# CORS
CORS_ORIGINS=["http://localhost:3000", "https://swissunihockey.app"]

# Push Notifications
VAPID_PUBLIC_KEY=
VAPID_PRIVATE_KEY=
VAPID_EMAIL=

# Celery
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2
```

---

## Deployment Guide

### Frontend (Vercel)

```bash
# Install Vercel CLI
npm i -g vercel

# Deploy
vercel

# Production deployment
vercel --prod

# Or connect GitHub repo for automatic deployments
```

### Backend (Railway)

```bash
# Install Railway CLI
npm i -g @railway/cli

# Login
railway login

# Initialize project
railway init

# Deploy
railway up

# Or use Docker
railway deploy --dockerfile Dockerfile
```

### Database (Supabase)

1. Create project at https://supabase.com
2. Get connection string
3. Update DATABASE_URL in .env
4. Run migrations: `alembic upgrade head`

---

## Cost Estimation (Monthly)

| Service | Plan | Cost |
|---------|------|------|
| Vercel | Hobby → Pro | $0 → $20 |
| Railway | Hobby → Pro | $5 → $20 |
| Supabase | Free → Pro | $0 → $25 |
| Upstash Redis | Free → Pay-as-go | $0 → $10 |
| Cloudflare | Free | $0 |
| Sentry | Developer | $0 |
| **Total** | **MVP** | **$5 - $75/mo** |

**For 10,000+ users**: ~$100-200/mo  
**For 100,000+ users**: ~$500-1000/mo

---

## Security Considerations

### Frontend
- [ ] Input sanitization (XSS prevention)
- [ ] Content Security Policy (CSP)
- [ ] HTTPS only
- [ ] Secure cookies
- [ ] Rate limiting
- [ ] CSRF protection

### Backend
- [ ] API authentication (JWT)
- [ ] Rate limiting (per IP/user)
- [ ] SQL injection prevention (ORM)
- [ ] CORS configuration
- [ ] Environment variables
- [ ] HTTPS/TLS
- [ ] Input validation (Pydantic)
- [ ] Password hashing (bcrypt)

---

## Performance Targets

### Frontend
- First Contentful Paint: < 1.0s
- Largest Contentful Paint: < 2.5s
- Time to Interactive: < 3.0s
- Cumulative Layout Shift: < 0.1
- Lighthouse Score: 95+

### Backend
- API Response Time: < 200ms (p95)
- WebSocket Latency: < 50ms
- Database Queries: < 50ms
- Uptime: 99.9%

---

**This stack will create a world-class, modern sports statistics platform! 🚀**
