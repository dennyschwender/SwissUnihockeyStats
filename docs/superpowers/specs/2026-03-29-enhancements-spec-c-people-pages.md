# Enhancements Spec C — People Pages (Referee & Coach)

## Overview

Two new detail pages for people involved in games:
- Referee details: query-based (no new DB model needed)
- Coach details: requires API research, new DB model, indexer integration

---

## Enhancement 1: Referee Details Page

### Problem
Referee names appear in `game_detail.html` but are not clickable or searchable. Users cannot see a referee's full game history.

### Design

**Backend — service (`backend/app/services/stats_service.py`):**

Add `get_referee_games(name, locale, limit=50)`:
```python
def get_referee_games(name: str, season_id: int | None, session) -> dict:
    q = session.query(Game).filter(
        or_(Game.referee_1 == name, Game.referee_2 == name)
    ).order_by(Game.game_date.desc())
    games = q.all()
    return {
        "name": name,
        "games": [
            {
                "game_id": g.id,
                "game_date": g.game_date.strftime("%d.%m.%Y") if g.game_date else "",
                "home_team": g.home_team_name,
                "away_team": g.away_team_name,
                "score": f"{g.home_score}–{g.away_score}" if g.home_score is not None else "",
                "league_name": g.league_name,
                "league_db_id": g.league_db_id,
            }
            for g in games
        ],
        "total": len(games),
    }
```

**Backend — route (`backend/app/main.py`):**

```python
@app.get("/{locale}/referee/{name}", response_class=HTMLResponse)
async def referee_detail(locale: str, name: str, request: Request):
    t = get_translations(locale)
    with db.session_scope() as session:
        data = stats_service.get_referee_games(unquote(name), session)
    return templates.TemplateResponse("referee_detail.html",
        {"request": request, "locale": locale, "t": t, "referee": data})
```

URL-encode referee names (spaces → `%20`) when linking. Use `urllib.parse.unquote` in the route.

**Template (`backend/templates/referee_detail.html`):**

Extends `base.html`. Shows:
- Page heading: referee name + total game count
- Table: Date | League | Home | Score | Away — each game row links to `/{locale}/game/{game_id}`
- Empty state if no games found

**Game detail links (`backend/templates/game_detail.html`):**

Replace plain referee name text with anchor tags:
```html
<a href="/{{ locale }}/referee/{{ game.referee_1 | urlencode }}">{{ game.referee_1 }}</a>
```
Apply to both `referee_1` and `referee_2` display locations.

**Global search extension (`backend/app/main.py` — search endpoint):**

In the existing global search handler, add a query for distinct referee names:
```python
referee_matches = session.query(Game.referee_1).filter(
    Game.referee_1.ilike(f"%{q}%"), Game.referee_1.isnot(None)
).union(
    session.query(Game.referee_2).filter(
        Game.referee_2.ilike(f"%{q}%"), Game.referee_2.isnot(None)
    )
).distinct().limit(5).all()
```
Return as type `"referee"` with `url = f"/{locale}/referee/{quote(name)}"`.

**i18n:** Add `referee` section with keys: `page_title`, `games_count`, `no_games`.

**Tests:** Unit test `get_referee_games` with two games where `referee_1` matches and one where `referee_2` matches. Assert correct game count and date formatting.

---

## Enhancement 2: Coach Details Page

### Problem
Coaches are not visible anywhere in the app. Team and game detail pages show lineups and referees but not the coaching staff. There is no way to navigate to a coach's history.

### Design

**API research:** The Swiss Unihockey API has a staff endpoint: `GET /teams/{team_id}/staff` (observed at `https://myapp.swissunihockey.ch/#/staff/{person_id}`). `SwissUnihockeyClient` needs a new method `get_team_staff(team_id)` — returns a list of staff members with fields: `person_id`, `first_name`, `last_name`, `role` (e.g. `"Headcoach"`, `"Assistantcoach"`).

**New DB model (`backend/app/models.py`):**

```python
class Staff(Base):
    __tablename__ = "staff"
    id = Column(Integer, primary_key=True)           # person_id from API
    season_id = Column(Integer, primary_key=True)    # composite PK
    team_id = Column(Integer, nullable=False)
    team_name = Column(String, nullable=True)
    league_db_id = Column(Integer, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    role = Column(String, nullable=True)             # Headcoach / Assistantcoach
    bio_url = Column(String, nullable=True)          # from staff endpoint if available
```

`session.merge()` on `(id, season_id)` for idempotent upsert.

**Indexer (`backend/app/services/data_indexer.py`):**

Add `index_team_staff(team_id, season_id, session)`:
- Call `client.get_team_staff(team_id)`
- For each staff member: upsert into `Staff` table
- Only headcoach and assistantcoach roles indexed (skip physiotherapists, etc.)

Hook into the existing team indexing loop — call after `index_team_games`. Gated by tier ≤ 2 (same as player stats).

**Service (`backend/app/services/stats_service.py`):**

Add `get_coach_detail(person_id, session)`:
```python
def get_coach_detail(person_id: int, session) -> dict | None:
    rows = session.query(Staff).filter(Staff.id == person_id)\
        .order_by(Staff.season_id.desc()).all()
    if not rows:
        return None
    latest = rows[0]
    return {
        "person_id": person_id,
        "name": f"{latest.first_name} {latest.last_name}".strip(),
        "role": latest.role,
        "seasons": [
            {
                "season_id": r.season_id,
                "season_text": _season_text(r.season_id),
                "team_name": r.team_name,
                "team_db_id": r.team_id,
                "league_db_id": r.league_db_id,
                "role": r.role,
            }
            for r in rows
        ],
    }
```

**Route (`backend/app/main.py`):**

```python
@app.get("/{locale}/coach/{person_id}", response_class=HTMLResponse)
async def coach_detail(locale: str, person_id: int, request: Request):
    t = get_translations(locale)
    with db.session_scope() as session:
        coach = stats_service.get_coach_detail(person_id, session)
    if not coach:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse("coach_detail.html",
        {"request": request, "locale": locale, "t": t, "coach": coach})
```

**Template (`backend/templates/coach_detail.html`):**

Extends `base.html`. Shows:
- Heading: coach name + current role
- Season history table: Season | Role | Team | League — team links to `/{locale}/team/{team_db_id}`, league links to `/{locale}/league/{league_db_id}`
- Empty state for coaches with no indexed seasons

**Show coach in team detail (`backend/templates/team_detail.html`):**

In the team header (near the roster tab), add a "Head Coach" line:
```
Head Coach: <a href="/{locale}/coach/{coach.person_id}">{{ coach.name }}</a>
```
Service change: `get_team_detail` adds `"head_coach": {person_id, name}` or `None`.

**Show coach in game detail (`backend/templates/game_detail.html`):**

In the game header section, below referee names, add:
```
Home Coach: <a href="...">Name</a>  |  Away Coach: <a href="...">Name</a>
```
Service change: `get_game_detail` (or equivalent) looks up `Staff` for home/away team for the game's season.

**Global search extension:**

Add staff name search alongside the referee search — query `Staff` by `first_name + last_name ILIKE %q%`, return type `"coach"` with link to `/{locale}/coach/{person_id}`.

**i18n:** Add `coach` section with keys: `page_title`, `head_coach`, `assistant_coach`, `no_seasons`, `season_history`.

**Tests:**
- Unit test `get_coach_detail`: assert seasons ordered desc, `name` combines first+last
- Unit test `index_team_staff`: mock API response, assert `Staff` rows upserted with correct fields

---

## Files Changed

| File | Change |
|---|---|
| `backend/app/models.py` | Add `Staff` model |
| `backend/app/services/api_client.py` | Add `get_team_staff(team_id)` method |
| `backend/app/services/data_indexer.py` | Add `index_team_staff`, hook into team indexing loop |
| `backend/app/services/stats_service.py` | Add `get_referee_games`, `get_coach_detail`; extend `get_team_detail` with head coach; extend game detail with coaches |
| `backend/app/main.py` | Add `referee_detail` and `coach_detail` routes; extend global search |
| `backend/templates/referee_detail.html` | New page |
| `backend/templates/coach_detail.html` | New page |
| `backend/templates/game_detail.html` | Referee names → links; add coach names |
| `backend/templates/team_detail.html` | Add head coach line in team header |
| `backend/locales/*/messages.json` | Add `referee` and `coach` i18n sections |
| `backend/tests/test_stats_service.py` | Tests for `get_referee_games`, `get_coach_detail` |
| `backend/tests/test_data_indexer.py` | Test for `index_team_staff` |
