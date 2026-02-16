# 🚀 Quick Start Guide - Build MVP in 4 Weeks

## Week 1: Foundation & Setup

### Day 1-2: Project Setup

**1. Create Frontend Repository**

```bash
# Navigate to your projects directory
cd "C:\Users\denny.schwender\projects"  # or wherever you want

# Create Next.js app
npx create-next-app@latest swiss-unihockey-web --typescript --tailwind --app --src-dir --import-alias "@/*"

cd swiss-unihockey-web

# Install core dependencies
npm install @tanstack/react-query zustand framer-motion
npm install @radix-ui/react-dialog @radix-ui/react-dropdown-menu @radix-ui/react-tabs
npm install lucide-react date-fns class-variance-authority clsx tailwind-merge

# Install development dependencies
npm install -D @types/node prettier prettier-plugin-tailwindcss

# Install shadcn/ui
npx shadcn@latest init
```

**Configure shadcn/ui when prompted:**
```
✔ Would you like to use TypeScript? yes
✔ Which style would you like to use? › Default
✔ Which color would you like to use as base color? › Red (Swiss colors!)
✔ Where is your global CSS file? › src/app/globals.css
✔ Would you like to use CSS variables for colors? › yes
✔ Where is your tailwind.config.js located? › tailwind.config.ts
✔ Configure the import alias for components: › @/components
✔ Configure the import alias for utils: › @/lib/utils
```

**2. Install shadcn/ui components**

```bash
# Essential components for sports app
npx shadcn@latest add button card badge avatar tabs dialog input
npx shadcn@latest add dropdown-menu separator skeleton
```

**3. Set up version control**

```bash
git init
git add .
git commit -m "Initial commit: Next.js sports app setup"

# Create GitHub repository (optional but recommended)
gh repo create swiss-unihockey-web --public --source=. --push
```

**4. Create Backend Repository**

```bash
cd ..
mkdir swiss-unihockey-api
cd swiss-unihockey-api

# Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1  # Windows

# Install FastAPI and dependencies
pip install fastapi uvicorn[standard] sqlalchemy asyncpg psycopg2-binary
pip install pydantic pydantic-settings python-dotenv
pip install redis aioredis httpx
pip install alembic pytest pytest-asyncio

# Save requirements
pip freeze > requirements.txt

# Create project structure
mkdir -p app/{api/v1,models,schemas,services,utils}
ni app/__init__.py, app/main.py, app/config.py, app/database.py
ni .env, .gitignore, README.md

git init
git add .
git commit -m "Initial commit: FastAPI backend setup"
```

### Day 3-4: Copy API Client & Basic Backend

**1. Copy existing API client to backend**

```bash
# From swiss-unihockey-api directory
cp -r "../99 - Scripting/swissunihockey/api" ./app/swissunihockey_api
```

**2. Create basic FastAPI app** (app/main.py):

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="SwissUnihockey API",
    description="Modern API for Swiss Unihockey statistics",
    version="1.0.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Next.js dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "SwissUnihockey API v1.0", "status": "online"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

# Import routers
from app.api.v1 import clubs, leagues, players
app.include_router(clubs.router, prefix="/api/v1", tags=["clubs"])
app.include_router(leagues.router, prefix="/api/v1", tags=["leagues"])
app.include_router(players.router, prefix="/api/v1", tags=["players"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

**3. Create first API endpoints** (app/api/v1/clubs.py):

```python
from fastapi import APIRouter, HTTPException
from app.swissunihockey_api.client import SwissUnihockeyClient
from typing import List
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

# Initialize API client
client = SwissUnihockeyClient(
    base_url="https://api-v2.swissunihockey.ch",
    locale="de-CH"
)

@router.get("/clubs")
async def get_clubs():
    """Get all Swiss Unihockey clubs"""
    try:
        clubs = client.get_clubs()
        logger.info(f"Fetched {len(clubs)} clubs")
        return {"count": len(clubs), "data": clubs}
    except Exception as e:
        logger.error(f"Error fetching clubs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/clubs/{club_id}")
async def get_club(club_id: int):
    """Get specific club by ID"""
    try:
        clubs = client.get_clubs()
        club = next((c for c in clubs if c.get("club_id") == club_id), None)
        
        if not club:
            raise HTTPException(status_code=404, detail="Club not found")
        
        return club
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching club {club_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

**Similar files for leagues.py and players.py**

**4. Test backend**

```bash
# Run FastAPI server
uvicorn app.main:app --reload

# Test in browser
# http://localhost:8000/docs  (Swagger UI)
# http://localhost:8000/api/v1/clubs
```

### Day 5-7: Frontend Shell & Design System

**1. Update globals.css with Swiss Unihockey brand colors**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    /* Swiss Unihockey brand colors */
    --primary: 0 100% 45%;      /* Swiss red #E30613 */
    --primary-foreground: 0 0% 100%;
    
    --secondary: 217 100% 33%;   /* Swiss blue #003DA5 */
    --secondary-foreground: 0 0% 100%;
    
    --background: 0 0% 100%;
    --foreground: 0 0% 10%;
    
    --muted: 0 0% 96%;
    --muted-foreground: 0 0% 45%;
    
    --accent: 0 0% 96%;
    --accent-foreground: 0 0% 10%;
    
    --card: 0 0% 100%;
    --card-foreground: 0 0% 10%;
    
    --border: 0 0% 90%;
    --input: 0 0% 90%;
    --ring: 0 100% 45%;
    
    --radius: 0.5rem;
  }

  .dark {
    --primary: 0 95% 55%;
    --primary-foreground: 0 0% 0%;
    
    --secondary: 217 90% 60%;
    --secondary-foreground: 0 0% 100%;
    
    --background: 0 0% 6%;
    --foreground: 0 0% 95%;
    
    --muted: 0 0% 15%;
    --muted-foreground: 0 0% 65%;
    
    --accent: 0 0% 15%;
    --accent-foreground: 0 0% 95%;
    
    --card: 0 0% 10%;
    --card-foreground: 0 0% 95%;
    
    --border: 0 0% 18%;
    --input: 0 0% 18%;
    --ring: 0 90% 55%;
  }
}

@layer base {
  * {
    @apply border-border;
  }
  body {
    @apply bg-background text-foreground;
    font-feature-settings: "rlig" 1, "calt" 1;
  }
}
```

**2. Create app layout** (src/app/layout.tsx):

```tsx
import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "SwissUnihockey Stats - Modern Statistics Platform",
  description: "Real-time Swiss Unihockey statistics, live scores, and player analytics",
  manifest: "/manifest.json",
  themeColor: "#E30613",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="de" suppressHydrationWarning>
      <body className={inter.className}>
        <div className="min-h-screen bg-background">
          {children}
        </div>
      </body>
    </html>
  );
}
```

**3. Create homepage** (src/app/page.tsx):

```tsx
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Trophy, Users, Calendar, TrendingUp } from "lucide-react";

export default function Home() {
  return (
    <main className="container mx-auto px-4 py-8">
      {/* Hero Section */}
      <div className="text-center mb-12">
        <h1 className="text-5xl font-bold mb-4 bg-gradient-to-r from-primary to-secondary bg-clip-text text-transparent">
          SwissUnihockey Stats
        </h1>
        <p className="text-xl text-muted-foreground">
          Die moderne Statistik-Plattform für Schweizer Unihockey
        </p>
      </div>

      {/* Feature Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-12">
        <Card>
          <CardHeader>
            <Trophy className="w-8 h-8 text-primary mb-2" />
            <CardTitle>Live Scores</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-muted-foreground">
              Echtzeit-Resultate aller Spiele
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <Users className="w-8 h-8 text-primary mb-2" />
            <CardTitle>Spielerstatistiken</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-muted-foreground">
              Detaillierte Spielerprofile
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <Calendar className="w-8 h-8 text-primary mb-2" />
            <CardTitle>Spielpläne</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-muted-foreground">
              Alle Spiele auf einen Blick
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <TrendingUp className="w-8 h-8 text-primary mb-2" />
            <CardTitle>Analytics</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-muted-foreground">
              Tiefgehende Analysen
            </p>
          </CardContent>
        </Card>
      </div>

      {/* CTA */}
      <div className="text-center">
        <Button size="lg" className="text-lg px-8">
          Jetzt entdecken
        </Button>
      </div>
    </main>
  );
}
```

**4. Run frontend**

```bash
npm run dev
# Open http://localhost:3000
```

---

## Week 2: Core Features (Standings & Players)

### Implement League Standings Page

**1. Create API hook** (src/lib/api/hooks.ts):

```typescript
import { useQuery } from '@tanstack/react-query';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export const useLeagueStandings = (leagueId: number, season: number) => {
  return useQuery({
    queryKey: ['standings', leagueId, season],
    queryFn: async () => {
      const res = await fetch(
        `${API_BASE}/api/v1/leagues/${leagueId}/standings?season=${season}`
      );
      if (!res.ok) throw new Error('Failed to fetch standings');
      return res.json();
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
};

export const useTopScorers = (leagueId: number, season: number) => {
  return useQuery({
    queryKey: ['topscorers', leagueId, season],
    queryFn: async () => {
      const res = await fetch(
        `${API_BASE}/api/v1/players/topscorers?league=${leagueId}&season=${season}`
      );
      if (!res.ok) throw new Error('Failed to fetch top scorers');
      return res.json();
    },
    staleTime: 5 * 60 * 1000,
  });
};
```

**2. Create standings table component** (src/components/leagues/StandingsTable.tsx):

```typescript
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

interface StandingsTableProps {
  teams: Array<{
    rank: number;
    team_name: string;
    games: number;
    wins: number;
    losses: number;
    goals_for: number;
    goals_against: number;
    points: number;
  }>;
}

export function StandingsTable({ teams }: StandingsTableProps) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-12">#</TableHead>
          <TableHead>Team</TableHead>
          <TableHead className="text-center">S</TableHead>
          <TableHead className="text-center">S</TableHead>
          <TableHead className="text-center">N</TableHead>
          <TableHead className="text-center">T+</TableHead>
          <TableHead className="text-center">T-</TableHead>
          <TableHead className="text-center font-bold">Pkt</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {teams.map((team) => (
          <TableRow key={team.rank}>
            <TableCell className="font-medium">{team.rank}</TableCell>
            <TableCell className="font-semibold">{team.team_name}</TableCell>
            <TableCell className="text-center">{team.games}</TableCell>
            <TableCell className="text-center">{team.wins}</TableCell>
            <TableCell className="text-center">{team.losses}</TableCell>
            <TableCell className="text-center">{team.goals_for}</TableCell>
            <TableCell className="text-center">{team.goals_against}</TableCell>
            <TableCell className="text-center font-bold">{team.points}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
```

**3. Create leagues page** (src/app/leagues/[id]/page.tsx):

```typescript
'use client';

import { useParams } from 'next/navigation';
import { useLeagueStandings } from '@/lib/api/hooks';
import { StandingsTable } from '@/components/leagues/StandingsTable';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

export default function LeaguePage() {
  const params = useParams();
  const leagueId = Number(params.id);
  const season = 2025;

  const { data, isLoading, error } = useLeagueStandings(leagueId, season);

  if (isLoading) {
    return (
      <div className="container mx-auto px-4 py-8">
        <Skeleton className="h-12 w-64 mb-6" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }

  if (error) {
    return <div>Error loading standings</div>;
  }

  return (
    <div className="container mx-auto px-4 py-8">
      <h1 className="text-4xl font-bold mb-6">Liga Tabelle</h1>
      
      <Card>
        <CardHeader>
          <CardTitle>Saison 2025/26</CardTitle>
        </CardHeader>
        <CardContent>
          <StandingsTable teams={data?.teams || []} />
        </CardContent>
      </Card>
    </div>
  );
}
```

### Implement Top Scorers Page

Similar pattern - create component, hook, and page.

---

## Week 3: Live Scores & Real-time Features

### Implement WebSocket for Live Scores

**Backend** (app/api/v1/live.py):

```python
from fastapi import APIRouter, WebSocket
import asyncio
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.websocket("/ws/live-scores")
async def live_scores_websocket(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket client connected")
    
    try:
        while True:
            # Fetch live games from SwissUnihockey API
            live_games = await get_live_games()
            
            # Send to client
            await websocket.send_json({
                "type": "live_update",
                "data": live_games,
                "timestamp": datetime.now().isoformat()
            })
            
            # Update every 10 seconds
            await asyncio.sleep(10)
            
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        logger.info("WebSocket client disconnected")

async def get_live_games():
    # Implementation: fetch from SwissUnihockey API
    # Filter for games with status = "live"
    pass
```

**Frontend** (src/hooks/useLiveScores.ts):

```typescript
import { useEffect, useState } from 'react';

export const useLiveScores = () => {
  const [scores, setScores] = useState([]);
  const [isConnected, setIsConnected] = useState(false);

  useEffect(() => {
    const ws = new WebSocket('ws://localhost:8000/api/v1/ws/live-scores');

    ws.onopen = () => {
      console.log('WebSocket connected');
      setIsConnected(true);
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setScores(data.data);
    };

    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
      setIsConnected(false);
    };

    ws.onclose = () => {
      console.log('WebSocket disconnected');
      setIsConnected(false);
    };

    return () => ws.close();
  }, []);

  return { scores, isConnected };
};
```

---

## Week 4: Mobile Polish & PWA

### Make it Mobile-First

**1. Add mobile navigation**
**2. Add touch gestures**
**3. Optimize images**
**4. Add loading states**

### Convert to PWA

**1. Install next-pwa**

```bash
npm install next-pwa workbox-webpack-plugin
```

**2. Configure next.config.js**

```javascript
const withPWA = require('next-pwa')({
  dest: 'public',
  register: true,
  skipWaiting: true,
});

module.exports = withPWA({
  reactStrictMode: true,
});
```

**3. Create manifest.json** (public/manifest.json):

```json
{
  "name": "SwissUnihockey Stats",
  "short_name": "CH Unihockey",
  "description": "Modern Swiss Unihockey statistics platform",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#ffffff",
  "theme_color": "#E30613",
  "icons": [
    {
      "src": "/icon-192.png",
      "sizes": "192x192",
      "type": "image/png"
    },
    {
      "src": "/icon-512.png",
      "sizes": "512x512",
      "type": "image/png"
    }
  ]
}
```

---

## 🎯 MVP Checklist (End of Week 4)

### Features
- [x] Homepage with hero
- [x] League standings table
- [x] Top scorers leaderboard
- [x] Player profile pages
- [x] Team pages
- [x] Game schedule
- [x] Live scores (basic)
- [x] Mobile responsive
- [x] PWA ready
- [x] Dark mode

### Technical
- [x] Next.js 15 setup
- [x] FastAPI backend
- [x] API integration
- [x] TypeScript types
- [x] TailwindCSS styling
- [x] React Query caching
- [x] Error handling
- [x] Loading states

### Deploy
- [x] Frontend to Vercel
- [x] Backend to Railway
- [x] Domain setup
- [x] SSL certificate
- [x] Analytics

---

## 📝 Daily Workflow Tips

**Morning (30 min)**
1. Review yesterday's work
2. Check GitHub issues
3. Plan today's tasks

**Development (6-8 hours)**
1. Work in 2-hour sprints
2. Commit frequently
3. Test on real device
4. Take breaks

**Evening (30 min)**
1. Push code to GitHub
2. Update TODO list
3. Test on mobile
4. Document learnings

---

## 🆘 Troubleshooting

### CORS errors
```python
# backend: app/main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Temporarily for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Build errors
```bash
# Clear Next.js cache
rm -rf .next
npm run build
```

### API not responding
```bash
# Check backend is running
curl http://localhost:8000/health
```

---

**You can build an amazing product in 4 weeks! Let's go! 🚀**
