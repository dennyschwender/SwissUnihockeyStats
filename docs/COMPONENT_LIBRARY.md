# 🎨 Component Library - Copy-Paste Ready Code

## Core UI Components for Sports App

### 1. Live Score Card (Home Page)

```typescript
// components/games/LiveScoreCard.tsx
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Clock } from "lucide-react";

interface LiveScoreCardProps {
  game: {
    id: number;
    homeTeam: string;
    awayTeam: string;
    homeScore: number;
    awayScore: number;
    period: string;
    timeRemaining: string;
  };
}

export function LiveScoreCard({ game }: LiveScoreCardProps) {
  return (
    <Card className="cursor-pointer hover:shadow-lg transition-shadow">
      <CardContent className="p-4">
        <div className="flex items-center justify-between mb-3">
          <Badge variant="destructive" className="animate-pulse">
            🔴 LIVE
          </Badge>
          <div className="flex items-center text-sm text-muted-foreground">
            <Clock className="w-4 h-4 mr-1" />
            <span>{game.timeRemaining}</span>
          </div>
        </div>

        <div className="grid grid-cols-[1fr,auto,1fr] items-center gap-4">
          {/* Home Team */}
          <div className="text-right">
            <p className="font-semibold text-lg">{game.homeTeam}</p>
          </div>

          {/* Score */}
          <div className="flex items-center gap-3 px-4">
            <span className="text-3xl font-bold">{game.homeScore}</span>
            <span className="text-muted-foreground">:</span>
            <span className="text-3xl font-bold">{game.awayScore}</span>
          </div>

          {/* Away Team */}
          <div className="text-left">
            <p className="font-semibold text-lg">{game.awayTeam}</p>
          </div>
        </div>

        <div className="mt-3 text-center">
          <Badge variant="outline">{game.period}</Badge>
        </div>
      </CardContent>
    </Card>
  );
}
```

**Usage:**

```tsx
<LiveScoreCard
  game={{
    id: 1,
    homeTeam: "UHC Thun",
    awayTeam: "Uster",
    homeScore: 5,
    awayScore: 3,
    period: "2. Drittel",
    timeRemaining: "12:35"
  }}
/>
```

---

### 2. Player Stats Card

```typescript
// components/players/PlayerStatsCard.tsx
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Trophy, Target, Users } from "lucide-react";

interface PlayerStatsCardProps {
  player: {
    id: number;
    name: string;
    number: number;
    photo?: string;
    team: string;
    position: string;
    stats: {
      games: number;
      goals: number;
      assists: number;
      points: number;
    };
  };
}

export function PlayerStatsCard({ player }: PlayerStatsCardProps) {
  const { stats } = player;

  return (
    <Card className="hover:shadow-lg transition-shadow">
      <CardHeader className="pb-3">
        <div className="flex items-center gap-4">
          <Avatar className="w-16 h-16">
            <AvatarImage src={player.photo} alt={player.name} />
            <AvatarFallback className="text-lg font-bold">
              {player.number}
            </AvatarFallback>
          </Avatar>
          <div className="flex-1">
            <h3 className="font-bold text-lg">{player.name}</h3>
            <p className="text-sm text-muted-foreground">{player.team}</p>
            <Badge variant="secondary" className="mt-1">
              {player.position}
            </Badge>
          </div>
        </div>
      </CardHeader>

      <CardContent>
        <div className="grid grid-cols-4 gap-4 text-center">
          <div>
            <p className="text-2xl font-bold">{stats.games}</p>
            <p className="text-xs text-muted-foreground">Spiele</p>
          </div>
          <div className="flex flex-col items-center">
            <div className="flex items-center gap-1">
              <Target className="w-4 h-4 text-primary" />
              <p className="text-2xl font-bold text-primary">{stats.goals}</p>
            </div>
            <p className="text-xs text-muted-foreground">Tore</p>
          </div>
          <div className="flex flex-col items-center">
            <div className="flex items-center gap-1">
              <Users className="w-4 h-4 text-secondary" />
              <p className="text-2xl font-bold text-secondary">{stats.assists}</p>
            </div>
            <p className="text-xs text-muted-foreground">Assists</p>
          </div>
          <div className="flex flex-col items-center">
            <div className="flex items-center gap-1">
              <Trophy className="w-4 h-4 text-yellow-500" />
              <p className="text-2xl font-bold">{stats.points}</p>
            </div>
            <p className="text-xs text-muted-foreground">Punkte</p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
```

---

### 3. League Standings Table (Mobile-Optimized)

```typescript
// components/leagues/StandingsTable.tsx
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";

interface Team {
  rank: number;
  prevRank: number;
  teamName: string;
  logo?: string;
  games: number;
  wins: number;
  losses: number;
  draws: number;
  goalsFor: number;
  goalsAgainst: number;
  goalDiff: number;
  points: number;
}

interface StandingsTableProps {
  teams: Team[];
  highlightRanks?: number[];
}

export function StandingsTable({ teams, highlightRanks = [] }: StandingsTableProps) {
  const getRankChange = (current: number, prev: number) => {
    if (current < prev) return <TrendingUp className="w-4 h-4 text-green-500" />;
    if (current > prev) return <TrendingDown className="w-4 h-4 text-red-500" />;
    return <Minus className="w-4 h-4 text-muted-foreground" />;
  };

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-12">#</TableHead>
            <TableHead>Team</TableHead>
            <TableHead className="text-center hidden md:table-cell">S</TableHead>
            <TableHead className="text-center">S</TableHead>
            <TableHead className="text-center">N</TableHead>
            <TableHead className="text-center hidden sm:table-cell">U</TableHead>
            <TableHead className="text-center hidden lg:table-cell">T+</TableHead>
            <TableHead className="text-center hidden lg:table-cell">T-</TableHead>
            <TableHead className="text-center hidden md:table-cell">TD</TableHead>
            <TableHead className="text-center font-bold">Pkt</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {teams.map((team) => {
            const isHighlighted = highlightRanks.includes(team.rank);
            
            return (
              <TableRow
                key={team.rank}
                className={isHighlighted ? "bg-primary/5" : ""}
              >
                <TableCell>
                  <div className="flex items-center gap-2">
                    <span className="font-bold">{team.rank}</span>
                    {getRankChange(team.rank, team.prevRank)}
                  </div>
                </TableCell>

                <TableCell>
                  <div className="flex items-center gap-2">
                    {team.logo && (
                      <img
                        src={team.logo}
                        alt={team.teamName}
                        className="w-6 h-6 rounded-full hidden sm:block"
                      />
                    )}
                    <span className="font-semibold whitespace-nowrap">
                      {team.teamName}
                    </span>
                  </div>
                </TableCell>

                <TableCell className="text-center hidden md:table-cell">
                  {team.games}
                </TableCell>
                <TableCell className="text-center">{team.wins}</TableCell>
                <TableCell className="text-center">{team.losses}</TableCell>
                <TableCell className="text-center hidden sm:table-cell">
                  {team.draws}
                </TableCell>
                <TableCell className="text-center hidden lg:table-cell">
                  {team.goalsFor}
                </TableCell>
                <TableCell className="text-center hidden lg:table-cell">
                  {team.goalsAgainst}
                </TableCell>
                <TableCell className="text-center hidden md:table-cell">
                  <span className={team.goalDiff > 0 ? "text-green-600" : "text-red-600"}>
                    {team.goalDiff > 0 ? "+" : ""}{team.goalDiff}
                  </span>
                </TableCell>
                <TableCell className="text-center">
                  <Badge className="font-bold">{team.points}</Badge>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
```

---

### 4. Top Scorers List

```typescript
// components/players/TopScorersList.tsx
import { Card, CardContent } from "@/components/ui/card";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Trophy, Medal } from "lucide-react";

interface Scorer {
  rank: number;
  playerName: string;
  photo?: string;
  team: string;
  number: number;
  goals: number;
  assists: number;
  points: number;
}

interface TopScorersListProps {
  scorers: Scorer[];
  limit?: number;
}

export function TopScorersList({ scorers, limit = 10 }: TopScorersListProps) {
  const topScorers = scorers.slice(0, limit);

  const getMedalIcon = (rank: number) => {
    switch (rank) {
      case 1:
        return <Trophy className="w-5 h-5 text-yellow-500" />;
      case 2:
        return <Medal className="w-5 h-5 text-gray-400" />;
      case 3:
        return <Medal className="w-5 h-5 text-orange-600" />;
      default:
        return null;
    }
  };

  return (
    <div className="space-y-2">
      {topScorers.map((scorer) => (
        <Card
          key={scorer.rank}
          className="hover:shadow-md transition-shadow cursor-pointer"
        >
          <CardContent className="p-4">
            <div className="flex items-center gap-4">
              {/* Rank */}
              <div className="flex items-center justify-center w-10">
                {getMedalIcon(scorer.rank) || (
                  <span className="font-bold text-muted-foreground">
                    {scorer.rank}
                  </span>
                )}
              </div>

              {/* Player Avatar */}
              <Avatar>
                <AvatarImage src={scorer.photo} />
                <AvatarFallback>{scorer.number}</AvatarFallback>
              </Avatar>

              {/* Player Info */}
              <div className="flex-1 min-w-0">
                <p className="font-semibold truncate">{scorer.playerName}</p>
                <p className="text-sm text-muted-foreground truncate">
                  {scorer.team}
                </p>
              </div>

              {/* Stats */}
              <div className="flex gap-4 text-center">
                <div className="hidden sm:block">
                  <p className="text-sm font-bold">{scorer.goals}</p>
                  <p className="text-xs text-muted-foreground">T</p>
                </div>
                <div className="hidden sm:block">
                  <p className="text-sm font-bold">{scorer.assists}</p>
                  <p className="text-xs text-muted-foreground">A</p>
                </div>
                <div>
                  <p className="text-lg font-bold text-primary">
                    {scorer.points}
                  </p>
                  <p className="text-xs text-muted-foreground">Pkt</p>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
```

---

### 5. Game Schedule Card

```typescript
// components/games/GameScheduleCard.tsx
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Calendar, MapPin, Clock } from "lucide-react";
import { format, parseISO } from "date-fns";
import { de } from "date-fns/locale";

interface Game {
  id: number;
  homeTeam: string;
  awayTeam: string;
  homeLogo?: string;
  awayLogo?: string;
  dateTime: string;
  venue: string;
  league: string;
  status?: "scheduled" | "live" | "finished";
  homeScore?: number;
  awayScore?: number;
}

interface GameScheduleCardProps {
  game: Game;
  onClick?: () => void;
}

export function GameScheduleCard({ game, onClick }: GameScheduleCardProps) {
  const gameDate = parseISO(game.dateTime);
  const isLive = game.status === "live";
  const isFinished = game.status === "finished";

  return (
    <Card
      className="hover:shadow-lg transition-shadow cursor-pointer"
      onClick={onClick}
    >
      <CardContent className="p-4">
        {/* Header - League & Status */}
        <div className="flex items-center justify-between mb-3">
          <Badge variant="outline">{game.league}</Badge>
          {isLive && (
            <Badge variant="destructive" className="animate-pulse">
              🔴 LIVE
            </Badge>
          )}
          {isFinished && <Badge variant="secondary">Beendet</Badge>}
        </div>

        {/* Teams & Score */}
        <div className="space-y-2 mb-3">
          {/* Home Team */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 flex-1">
              {game.homeLogo && (
                <img
                  src={game.homeLogo}
                  alt={game.homeTeam}
                  className="w-8 h-8 rounded-full"
                />
              )}
              <span className="font-semibold">{game.homeTeam}</span>
            </div>
            {game.homeScore !== undefined && (
              <span className="text-2xl font-bold ml-4">{game.homeScore}</span>
            )}
          </div>

          {/* Away Team */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 flex-1">
              {game.awayLogo && (
                <img
                  src={game.awayLogo}
                  alt={game.awayTeam}
                  className="w-8 h-8 rounded-full"
                />
              )}
              <span className="font-semibold">{game.awayTeam}</span>
            </div>
            {game.awayScore !== undefined && (
              <span className="text-2xl font-bold ml-4">{game.awayScore}</span>
            )}
          </div>
        </div>

        {/* Date, Time & Venue */}
        <div className="flex flex-wrap gap-3 text-sm text-muted-foreground">
          <div className="flex items-center gap-1">
            <Calendar className="w-4 h-4" />
            <span>{format(gameDate, "EEE, dd.MM.yyyy", { locale: de })}</span>
          </div>
          <div className="flex items-center gap-1">
            <Clock className="w-4 h-4" />
            <span>{format(gameDate, "HH:mm")}</span>
          </div>
          <div className="flex items-center gap-1">
            <MapPin className="w-4 h-4" />
            <span>{game.venue}</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
```

---

### 6. Mobile Bottom Navigation

```typescript
// components/layout/BottomNav.tsx
"use client";

import { usePathname, useRouter } from "next/navigation";
import { Home, Trophy, Search, Star, User } from "lucide-react";

const navItems = [
  { icon: Home, label: "Home", href: "/" },
  { icon: Trophy, label: "Liga", href: "/leagues" },
  { icon: Search, label: "Suche", href: "/search" },
  { icon: Star, label: "Favoriten", href: "/favorites" },
  { icon: User, label: "Profil", href: "/profile" },
];

export function BottomNav() {
  const pathname = usePathname();
  const router = useRouter();

  return (
    <nav className="fixed bottom-0 left-0 right-0 bg-background border-t md:hidden z-50">
      <div className="flex justify-around items-center h-16">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = pathname === item.href;

          return (
            <button
              key={item.href}
              onClick={() => router.push(item.href)}
              className={`flex flex-col items-center justify-center flex-1 h-full transition-colors ${
                isActive
                  ? "text-primary"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <Icon className={`w-6 h-6 ${isActive ? "fill-current" : ""}`} />
              <span className="text-xs mt-1">{item.label}</span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
```

**Add to layout:**

```tsx
// app/layout.tsx
import { BottomNav } from "@/components/layout/BottomNav";

export default function RootLayout({ children }) {
  return (
    <html>
      <body>
        {children}
        <BottomNav />
        <div className="h-16 md:hidden" /> {/* Spacer */}
      </body>
    </html>
  );
}
```

---

### 7. Dark Mode Toggle

```typescript
// components/layout/ThemeToggle.tsx
"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
    >
      <Sun className="h-5 w-5 rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
      <Moon className="absolute h-5 w-5 rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
      <span className="sr-only">Toggle theme</span>
    </Button>
  );
}
```

**Install next-themes:**

```bash
npm install next-themes
```

**Add provider to layout:**

```tsx
// app/layout.tsx
import { ThemeProvider } from "next-themes";

export default function RootLayout({ children }) {
  return (
    <html suppressHydrationWarning>
      <body>
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
```

---

### 8. Loading Skeleton

```typescript
// components/ui/LoadingSkeleton.tsx
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

export function StandingsTableSkeleton() {
  return (
    <Card>
      <CardHeader>
        <Skeleton className="h-6 w-32" />
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {[...Array(10)].map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

export function PlayerCardSkeleton() {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-4">
          <Skeleton className="w-16 h-16 rounded-full" />
          <div className="space-y-2">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-3 w-24" />
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

export function GameScheduleSkeleton() {
  return (
    <div className="space-y-4">
      {[...Array(5)].map((_, i) => (
        <Card key={i}>
          <CardContent className="p-4">
            <div className="space-y-3">
              <Skeleton className="h-4 w-20" />
              <Skeleton className="h-6 w-full" />
              <Skeleton className="h-6 w-full" />
              <div className="flex gap-2">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-4 w-16" />
              </div>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
```

---

### 9. Pull-to-Refresh (Mobile)

```typescript
// hooks/usePullToRefresh.ts
import { useEffect, useRef, useState } from "react";

export function usePullToRefresh(onRefresh: () => Promise<void>) {
  const [isRefreshing, setIsRefreshing] = useState(false);
  const startY = useRef(0);
  const currentY = useRef(0);

  useEffect(() => {
    const handleTouchStart = (e: TouchEvent) => {
      if (window.scrollY === 0) {
        startY.current = e.touches[0].clientY;
      }
    };

    const handleTouchMove = (e: TouchEvent) => {
      if (window.scrollY === 0 && !isRefreshing) {
        currentY.current = e.touches[0].clientY;
        const diff = currentY.current - startY.current;
        
        if (diff > 100) {
          // Trigger refresh
          setIsRefreshing(true);
          onRefresh().finally(() => {
            setIsRefreshing(false);
            startY.current = 0;
            currentY.current = 0;
          });
        }
      }
    };

    window.addEventListener("touchstart", handleTouchStart);
    window.addEventListener("touchmove", handleTouchMove);

    return () => {
      window.removeEventListener("touchstart", handleTouchStart);
      window.removeEventListener("touchmove", handleTouchMove);
    };
  }, [onRefresh, isRefreshing]);

  return { isRefreshing };
}
```

**Usage:**

```tsx
const { isRefreshing } = usePullToRefresh(async () => {
  await refetch();
});

if (isRefreshing) {
  return <LoadingSpinner />;
}
```

---

### 10. Performance - Image Optimization

```typescript
// components/ui/OptimizedImage.tsx
import Image from "next/image";

interface OptimizedImageProps {
  src: string;
  alt: string;
  width?: number;
  height?: number;
  className?: string;
}

export function OptimizedImage({
  src,
  alt,
  width = 300,
  height = 300,
  className,
}: OptimizedImageProps) {
  // Handle external URLs
  const isExternal = src.startsWith("http");
  
  if (isExternal) {
    return (
      <Image
        src={src}
        alt={alt}
        width={width}
        height={height}
        className={className}
        loading="lazy"
        placeholder="blur"
        blurDataURL="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mN8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
      />
    );
  }

  return (
    <Image
      src={src}
      alt={alt}
      width={width}
      height={height}
      className={className}
      priority={false}
    />
  );
}
```

---

## 🎯 Complete Example Page

**Full League Standings Page:**

```tsx
// app/leagues/[id]/page.tsx
"use client";

import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StandingsTable } from "@/components/leagues/StandingsTable";
import { TopScorersList } from "@/components/players/TopScorersList";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { StandingsTableSkeleton } from "@/components/ui/LoadingSkeleton";
import { usePullToRefresh } from "@/hooks/usePullToRefresh";

export default function LeaguePage() {
  const params = useParams();
  const leagueId = Number(params.id);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["league", leagueId],
    queryFn: async () => {
      const res = await fetch(`/api/v1/leagues/${leagueId}`);
      return res.json();
    },
  });

  const { isRefreshing } = usePullToRefresh(async () => {
    await refetch();
  });

  if (isLoading || isRefreshing) {
    return <StandingsTableSkeleton />;
  }

  return (
    <div className="container mx-auto px-4 py-8 pb-24 md:pb-8">
      <h1 className="text-4xl font-bold mb-6">{data.league.name}</h1>

      <Tabs defaultValue="standings">
        <TabsList className="grid w-full grid-cols-2">
          <TabsTrigger value="standings">Tabelle</TabsTrigger>
          <TabsTrigger value="topscorers">Top Scorer</TabsTrigger>
        </TabsList>

        <TabsContent value="standings">
          <Card>
            <CardHeader>
              <CardTitle>Saison 2025/26</CardTitle>
            </CardHeader>
            <CardContent>
              <StandingsTable
                teams={data.standings}
                highlightRanks={[1, 2, 3]}
              />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="topscorers">
          <Card>
            <CardHeader>
              <CardTitle>Top Torschützen</CardTitle>
            </CardHeader>
            <CardContent>
              <TopScorersList scorers={data.topScorers} />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
```

---

**All components are copy-paste ready! Just adjust types and API endpoints! 🚀**
