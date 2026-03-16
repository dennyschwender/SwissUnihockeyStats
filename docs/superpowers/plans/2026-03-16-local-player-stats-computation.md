# Local PlayerStatistics Computation (T1–T3) Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace per-player API calls for `PlayerStatistics` with SQL aggregation over local `GamePlayer`/`GameEvent` rows for tiers 1–3, eliminating hours-long API polling.

**Architecture:** A new `compute_player_stats_for_season` method in `DataIndexer` aggregates stats from complete T1–T3 games; a separate `UnresolvedPlayerEvent` table captures events where name-matching fails; new scheduler policies replace the T1–T3 API stat jobs; T4–T6 are unchanged.

**Tech Stack:** SQLAlchemy 2.x, FastAPI, SQLite (WAL), pytest, Jinja2

---

## File Map

| File | Change |
|---|---|
| `backend/app/models/db_models.py` | Add `computed_from_local`/`local_computed_at` to `PlayerStatistics`; add `UnresolvedPlayerEvent` model |
| `backend/app/services/local_stats_aggregator.py` | **New** — aggregation + name-matching logic |
| `backend/app/services/data_indexer.py` | Add `compute_player_stats_for_season()`; wire tier filter to skip T1–T3 in `index_player_stats_for_season` |
| `backend/app/services/scheduler.py` | Add 3 `compute_player_stats` policies (T1/T2/T3); keep T4–T6 `player_stats` policies unchanged |
| `backend/app/main.py` | Add `compute_player_stats` to `_TASK_META`/`_TASK_LABELS`/`_run()`; add `/admin/unresolved-events` route |
| `backend/templates/admin_unresolved_events.html` | **New** — admin page listing `UnresolvedPlayerEvent` rows with dismiss action |
| `backend/locales/*/messages.json` | Add `admin.unresolved_events.*` keys |
| `backend/tests/test_local_stats_aggregator.py` | **New** — unit tests for all aggregation + name-matching logic |
| `backend/tests/test_local_stats_integration.py` | **New** — integration tests using in-memory DB |

---

## Chunk 1: Schema

### Task 1: Add columns to `PlayerStatistics` and new `UnresolvedPlayerEvent` model

**Files:**
- Modify: `backend/app/models/db_models.py`

**Context:** `PlayerStatistics` is at line 308. `GameSyncFailure` is at line 235 — follow that as a pattern for the new table. The `_utcnow` helper is at the top of the file. The `Base.metadata.create_all` + idempotent migration in `database.py` handles schema changes automatically — no Alembic needed.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_local_stats_integration.py`:

```python
"""Integration tests for local player stats computation."""
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.models.db_models import Base, PlayerStatistics, UnresolvedPlayerEvent


@pytest.fixture
def engine():
    e = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    yield e
    e.dispose()


def test_player_statistics_has_local_columns(engine):
    cols = {c["name"] for c in inspect(engine).get_columns("player_statistics")}
    assert "computed_from_local" in cols
    assert "local_computed_at" in cols


def test_unresolved_player_event_table_exists(engine):
    assert inspect(engine).has_table("unresolved_player_events")
    cols = {c["name"] for c in inspect(engine).get_columns("unresolved_player_events")}
    assert {"id", "game_id", "team_id", "raw_name", "event_type", "created_at",
            "resolved_at", "resolved_by"}.issubset(cols)
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && .venv/bin/pytest tests/test_local_stats_integration.py -v
```
Expected: FAIL — columns/table don't exist yet.

- [ ] **Step 3: Add `computed_from_local` and `local_computed_at` to `PlayerStatistics`**

In `backend/app/models/db_models.py`, after `last_updated` on `PlayerStatistics` (around line 329), add:

```python
    computed_from_local: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="0")
    local_computed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
```

- [ ] **Step 4: Add `UnresolvedPlayerEvent` model**

After `GameSyncFailure` (around line 245), add:

```python
class UnresolvedPlayerEvent(Base):
    """Player name from GameEvent that could not be matched to a GamePlayer row."""
    __tablename__ = "unresolved_player_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(Integer, ForeignKey("games.id"), nullable=False)
    team_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    season_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("seasons.id"), nullable=True)
    raw_name: Mapped[str] = mapped_column(String(200), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    resolved_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    __table_args__ = (
        Index("idx_unresolved_game", "game_id"),
        Index("idx_unresolved_unresolved", "resolved_at"),
    )
```

Also add `UnresolvedPlayerEvent` to the imports at top of `data_indexer.py` and `main.py` once it's needed.

- [ ] **Step 5: Run tests to verify pass**

```bash
cd backend && .venv/bin/pytest tests/test_local_stats_integration.py -v
```
Expected: PASS

- [ ] **Step 6: Run full test suite to check for regressions**

```bash
cd backend && .venv/bin/pytest --tb=short -q
```
Expected: All existing tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/db_models.py backend/tests/test_local_stats_integration.py
git commit -m "feat(schema): add computed_from_local to PlayerStatistics and UnresolvedPlayerEvent table"
```

---

## Chunk 2: Aggregation Service

### Task 2: Create `local_stats_aggregator.py`

**Files:**
- Create: `backend/app/services/local_stats_aggregator.py`
- Create: `backend/tests/test_local_stats_aggregator.py`

**Context:**
- `GamePlayer` fields: `player_id`, `team_id`, `game_id`, `season_id`, `goals`, `assists`, `penalty_minutes` (total pim). **No pen breakdown columns.**
- `GameEvent` fields: `game_id`, `team_id`, `season_id`, `event_type` (e.g. `"2'-Strafe"`, `"5'-Strafe"`, `"10'-Strafe"`, `"Technische Matchstrafe"`), `player` name string in `raw_data->>'player'`, `player_id` is always NULL.
- `Game.completeness_status`: only aggregate from `'complete'` games.
- `LEAGUE_TIERS` and `league_tier()` are in `data_indexer.py`; import them.
- Penalty event_type patterns (from data_indexer.py parsing): contains `"'-strafe"` (case-insensitive). Duration in minutes is parsed from the string prefix: `"2'"`, `"5'"`, `"10'"`, `"match"` / `"technische matchstrafe"`.
- `PlayerStatistics` unique key: `(player_id, season_id, league_abbrev)` — upsert on that.
- `league_abbrev` for locally-computed rows: derive from the League's name abbreviation. Simplest: use `League.name` first 20 chars, or store a dedicated abbrev. **Use `LeagueGroup.name` field** — it is already stored. Actually use `League.name` (not group name). Look up via `Game.group_id → LeagueGroup.league_id → League.name`.
- Per the spec: T3 does NOT get pen breakdown or plus_minus — only goals/assists/penalty_minutes/games_played.
- plus_minus: **not computable** from available data (requires ice-time tracking). Do not attempt; leave existing value or 0.

**Penalty minute classification from event_type string:**
```python
def _pen_bucket(event_type: str) -> str | None:
    et = event_type.lower()
    if "2'" in et: return "2min"
    if "5'" in et: return "5min"
    if "10'" in et: return "10min"
    if "match" in et or "technische" in et: return "match"
    return None  # unknown penalty type, ignore for breakdown
```

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_local_stats_aggregator.py`:

```python
"""Unit tests for local_stats_aggregator."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from unittest.mock import MagicMock
from contextlib import contextmanager

from app.models.db_models import (
    Base, Season, Club, Team, League, LeagueGroup,
    Game, GamePlayer, GameEvent, Player, PlayerStatistics,
    UnresolvedPlayerEvent, _utcnow,
)
from app.services.local_stats_aggregator import (
    _pen_bucket, aggregate_player_stats_for_season,
)


@pytest.fixture
def engine():
    e = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    yield e
    e.dispose()


@pytest.fixture
def mock_db(engine):
    db = MagicMock()
    @contextmanager
    def session_scope():
        with Session(engine) as s:
            yield s
            s.commit()
    db.session_scope = session_scope
    db.engine = engine
    return db


def _seed_complete_game(engine, tier=1):
    """Seed a minimal complete game with one player scoring a goal and getting a penalty."""
    with Session(engine) as s:
        season = Season(id=1, text="2025")
        s.add(season)
        s.flush()
        club = Club(id=1, season_id=1, name="TestClub")
        s.add(club)
        s.flush()
        team = Team(id=1, season_id=1, club_id=1, name="TestTeam", league_id=100)
        s.add(team)
        s.flush()
        league = League(id=1, season_id=1, league_id=100, game_class=1, name="NLA")
        s.add(league)
        s.flush()
        group = LeagueGroup(id=1, league_id=1, group_id=10, name="NLA")
        s.add(group)
        s.flush()
        player = Player(person_id=42, first_name="Max", last_name="Muster")
        s.add(player)
        s.flush()
        game = Game(
            id=1, season_id=1,
            home_team_id=1, away_team_id=1,
            status="finished", completeness_status="complete",
            home_score=3, away_score=1,
            group_id=10,
        )
        s.add(game)
        s.flush()
        gp = GamePlayer(
            game_id=1, player_id=42, team_id=1, season_id=1,
            is_home_team=True, goals=2, assists=1, penalty_minutes=2,
        )
        s.add(gp)
        # Goal event with matching player name
        ge_goal = GameEvent(
            game_id=1, team_id=1, season_id=1,
            event_type="Torschütze",
            raw_data={"player": "Max Muster", "event_type": "Torschütze", "time": "10:00", "team": "TestTeam"},
        )
        # Penalty event
        ge_pen = GameEvent(
            game_id=1, team_id=1, season_id=1,
            event_type="2'-Strafe",
            raw_data={"player": "Max Muster", "event_type": "2'-Strafe", "time": "15:00", "team": "TestTeam"},
        )
        s.add_all([ge_goal, ge_pen])
        s.commit()


# ── _pen_bucket tests ─────────────────────────────────────────────────────────

def test_pen_bucket_2min():
    assert _pen_bucket("2'-Strafe") == "2min"

def test_pen_bucket_5min():
    assert _pen_bucket("5'-Strafe") == "5min"

def test_pen_bucket_10min():
    assert _pen_bucket("10'-Strafe") == "10min"

def test_pen_bucket_match():
    assert _pen_bucket("Matchstrafe") == "match"

def test_pen_bucket_technische():
    assert _pen_bucket("Technische Matchstrafe") == "match"

def test_pen_bucket_unknown():
    assert _pen_bucket("Timeout") is None


# ── aggregate_player_stats_for_season tests ───────────────────────────────────

def test_aggregate_creates_player_statistics_row(engine, mock_db):
    _seed_complete_game(engine)
    count = aggregate_player_stats_for_season(mock_db, season_id=1, tiers=[1, 2, 3])
    assert count >= 1
    with Session(engine) as s:
        row = s.query(PlayerStatistics).filter_by(player_id=42, season_id=1).first()
        assert row is not None
        assert row.goals == 2
        assert row.assists == 1
        assert row.games_played == 1
        assert row.computed_from_local is True
        assert row.local_computed_at is not None


def test_aggregate_pen_breakdown_t1(engine, mock_db):
    _seed_complete_game(engine, tier=1)
    aggregate_player_stats_for_season(mock_db, season_id=1, tiers=[1])
    with Session(engine) as s:
        row = s.query(PlayerStatistics).filter_by(player_id=42, season_id=1).first()
        assert row.pen_2min == 1


def test_aggregate_skips_non_complete_games(engine, mock_db):
    _seed_complete_game(engine)
    # Mark game as post_game (incomplete)
    with Session(engine) as s:
        g = s.get(Game, 1)
        g.completeness_status = "post_game"
        s.commit()
    count = aggregate_player_stats_for_season(mock_db, season_id=1, tiers=[1, 2, 3])
    assert count == 0


def test_aggregate_no_games_returns_zero(engine, mock_db):
    # Empty DB
    with Session(engine) as s:
        s.add(Season(id=1, text="2025"))
        s.commit()
    count = aggregate_player_stats_for_season(mock_db, season_id=1, tiers=[1, 2, 3])
    assert count == 0


def test_unresolved_event_created_for_unknown_player(engine, mock_db):
    _seed_complete_game(engine)
    # Add a penalty event with a name that doesn't match any GamePlayer
    with Session(engine) as s:
        ge = GameEvent(
            game_id=1, team_id=1, season_id=1,
            event_type="2'-Strafe",
            raw_data={"player": "Unknown Player", "event_type": "2'-Strafe", "time": "20:00", "team": "TestTeam"},
        )
        s.add(ge)
        s.commit()
    aggregate_player_stats_for_season(mock_db, season_id=1, tiers=[1])
    with Session(engine) as s:
        unresolved = s.query(UnresolvedPlayerEvent).filter_by(game_id=1).all()
        assert any(u.raw_name == "Unknown Player" for u in unresolved)
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && .venv/bin/pytest tests/test_local_stats_aggregator.py -v
```
Expected: FAIL — `local_stats_aggregator` module doesn't exist.

- [ ] **Step 3: Create `backend/app/services/local_stats_aggregator.py`**

```python
"""Local aggregation of PlayerStatistics from GamePlayer/GameEvent rows.

For tiers 1–3 where game data is complete (completeness_status='complete'),
compute PlayerStatistics directly from stored per-game data instead of
calling the per-player API endpoint.

Penalty breakdown (pen_2min/pen_5min/pen_10min/pen_match) is only computed
for T1/T2 because T3 games don't include detailed event data.
plus_minus is not computed (requires ice-time tracking not available locally).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.db_models import (
    Game, GameEvent, GamePlayer, League, LeagueGroup,
    PlayerStatistics, UnresolvedPlayerEvent,
)
from app.services.data_indexer import LEAGUE_TIERS, league_tier

logger = logging.getLogger(__name__)

# Tiers that get penalty breakdown aggregated from GameEvent
_PEN_BREAKDOWN_TIERS = {1, 2}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _pen_bucket(event_type: str) -> str | None:
    """Classify a penalty event_type string into a bucket (2min/5min/10min/match).

    Returns None if the event type is not a recognisable penalty bucket.
    """
    et = event_type.lower()
    if "2'" in et:
        return "2min"
    if "5'" in et:
        return "5min"
    if "10'" in et:
        return "10min"
    if "match" in et or "technische" in et:
        return "match"
    return None


def _player_name_from_event(event: GameEvent) -> str | None:
    """Extract the player name string from a GameEvent's raw_data."""
    if event.raw_data and isinstance(event.raw_data, dict):
        return event.raw_data.get("player") or None
    return None


def _league_abbrev_for_game(game: Game, session: Session) -> str:
    """Resolve a short league abbreviation for a game via group → league."""
    if game.group_id is None:
        return "unknown"
    group = session.get(LeagueGroup, game.group_id)
    if group is None:
        return "unknown"
    league = session.get(League, group.league_id)
    if league is None:
        return "unknown"
    return (league.name or "unknown")[:20]


def _resolve_tier_for_game(game: Game, session: Session) -> int | None:
    """Return the tier (1–6) for a game, or None if not resolvable."""
    if game.group_id is None:
        return None
    group = session.get(LeagueGroup, game.group_id)
    if group is None:
        return None
    league = session.get(League, group.league_id)
    if league is None:
        return None
    return LEAGUE_TIERS.get(league.league_id, 6)


def aggregate_player_stats_for_season(
    db_service,
    season_id: int,
    tiers: Sequence[int] = (1, 2, 3),
) -> int:
    """Aggregate PlayerStatistics from local game data for the given tiers.

    Only processes games with completeness_status='complete'.
    Upserts PlayerStatistics rows with computed values.
    Creates UnresolvedPlayerEvent rows for penalty events where the player
    name cannot be matched to a GamePlayer row.

    Returns the number of PlayerStatistics rows created or updated.
    """
    tiers_set = set(tiers)
    updated = 0

    with db_service.session_scope() as session:
        # Find all complete games for this season in the target tiers
        games = (
            session.query(Game)
            .filter(
                Game.season_id == season_id,
                Game.completeness_status == "complete",
                Game.group_id.isnot(None),
            )
            .all()
        )

        # Filter to target tiers
        tier_games: list[tuple[Game, int, str]] = []
        for game in games:
            tier = _resolve_tier_for_game(game, session)
            if tier is not None and tier in tiers_set:
                abbrev = _league_abbrev_for_game(game, session)
                tier_games.append((game, tier, abbrev))

        if not tier_games:
            return 0

        # Collect all game_ids in target tier set
        game_ids = [g.id for g, _, _ in tier_games]
        tier_by_game = {g.id: t for g, t, _ in tier_games}
        abbrev_by_game = {g.id: a for g, _, a in tier_games}

        # ── Step 1: Aggregate from GamePlayer (goals, assists, pim, games_played) ──
        # GROUP BY player_id, team_id, season_id across all target games
        rows = (
            session.query(
                GamePlayer.player_id,
                GamePlayer.team_id,
                func.count(GamePlayer.game_id).label("games_played"),
                func.coalesce(func.sum(GamePlayer.goals), 0).label("goals"),
                func.coalesce(func.sum(GamePlayer.assists), 0).label("assists"),
                func.coalesce(func.sum(GamePlayer.penalty_minutes), 0).label("penalty_minutes"),
            )
            .filter(
                GamePlayer.season_id == season_id,
                GamePlayer.game_id.in_(game_ids),
            )
            .group_by(GamePlayer.player_id, GamePlayer.team_id)
            .all()
        )

        # Determine league_abbrev per (player_id, team_id) — use most common game's abbrev
        # Simplified: use the abbrev of the first complete game for that player's team
        gp_game_rows = (
            session.query(GamePlayer.player_id, GamePlayer.team_id, GamePlayer.game_id)
            .filter(
                GamePlayer.season_id == season_id,
                GamePlayer.game_id.in_(game_ids),
            )
            .all()
        )
        # Map (player_id, team_id) → first game_id (for abbrev lookup)
        first_game: dict[tuple[int, int], int] = {}
        for pid, tid, gid in gp_game_rows:
            if (pid, tid) not in first_game:
                first_game[(pid, tid)] = gid

        # ── Step 2: Aggregate penalty breakdown from GameEvent (T1/T2 only) ──
        # Build a map: (player_id, team_id) → {2min: N, 5min: N, 10min: N, match: N}
        pen_breakdown: dict[tuple[int, int], dict[str, int]] = {}

        penalty_events = (
            session.query(GameEvent)
            .filter(
                GameEvent.season_id == season_id,
                GameEvent.game_id.in_(game_ids),
                GameEvent.event_type.ilike("%'-strafe%"),
            )
            .all()
        )

        # Build a name→player_id lookup per (game_id, team_id) from GamePlayer
        name_map: dict[tuple[int, int], dict[str, int]] = {}
        gp_all = (
            session.query(GamePlayer)
            .filter(
                GamePlayer.season_id == season_id,
                GamePlayer.game_id.in_(game_ids),
            )
            .all()
        )
        # We need player names — join to Player table
        from app.models.db_models import Player as PlayerModel
        player_names: dict[int, str] = {
            p.person_id: f"{p.first_name or ''} {p.last_name or ''}".strip()
            for p in session.query(PlayerModel)
            .filter(PlayerModel.person_id.in_({gp.player_id for gp in gp_all}))
            .all()
        }
        for gp in gp_all:
            key = (gp.game_id, gp.team_id)
            name = player_names.get(gp.player_id, "").lower()
            if name:
                name_map.setdefault(key, {})[name] = gp.player_id

        # Process penalty events — only for T1/T2 games
        seen_unresolved: set[tuple] = set()
        for evt in penalty_events:
            if tier_by_game.get(evt.game_id) not in _PEN_BREAKDOWN_TIERS:
                continue
            bucket = _pen_bucket(evt.event_type)
            if bucket is None:
                continue
            raw_name = _player_name_from_event(evt)
            if not raw_name:
                continue
            # Try exact name match (case-insensitive)
            key = (evt.game_id, evt.team_id)
            pid = name_map.get(key, {}).get(raw_name.lower())
            if pid is None:
                # Unresolved — record once per (game, team, name)
                unresolved_key = (evt.game_id, evt.team_id, raw_name)
                if unresolved_key not in seen_unresolved:
                    seen_unresolved.add(unresolved_key)
                    existing = (
                        session.query(UnresolvedPlayerEvent)
                        .filter_by(
                            game_id=evt.game_id,
                            team_id=evt.team_id,
                            raw_name=raw_name,
                            resolved_at=None,
                        )
                        .first()
                    )
                    if existing is None:
                        session.add(UnresolvedPlayerEvent(
                            game_id=evt.game_id,
                            team_id=evt.team_id,
                            season_id=evt.season_id,
                            raw_name=raw_name,
                            event_type=evt.event_type,
                            created_at=_utcnow(),
                        ))
                continue
            # Found player — accumulate penalty bucket
            tid = evt.team_id
            pen_breakdown.setdefault((pid, tid), {"2min": 0, "5min": 0, "10min": 0, "match": 0})
            pen_breakdown[(pid, tid)][bucket] += 1

        # ── Step 3: Upsert PlayerStatistics rows ──
        now = _utcnow()
        for row in rows:
            pid, tid = row.player_id, row.team_id
            abbrev = abbrev_by_game.get(first_game.get((pid, tid), -1), "unknown")
            breakdown = pen_breakdown.get((pid, tid), {})

            existing = (
                session.query(PlayerStatistics)
                .filter_by(player_id=pid, season_id=season_id, league_abbrev=abbrev)
                .first()
            )
            if existing is None:
                obj = PlayerStatistics(
                    player_id=pid,
                    season_id=season_id,
                    team_id=tid,
                    league_abbrev=abbrev,
                    games_played=row.games_played,
                    goals=row.goals,
                    assists=row.assists,
                    points=(row.goals or 0) + (row.assists or 0),
                    penalty_minutes=row.penalty_minutes,
                    pen_2min=breakdown.get("2min", 0),
                    pen_5min=breakdown.get("5min", 0),
                    pen_10min=breakdown.get("10min", 0),
                    pen_match=breakdown.get("match", 0),
                    computed_from_local=True,
                    local_computed_at=now,
                    last_updated=now,
                )
                session.add(obj)
            else:
                existing.games_played = row.games_played
                existing.goals = row.goals
                existing.assists = row.assists
                existing.points = (row.goals or 0) + (row.assists or 0)
                existing.penalty_minutes = row.penalty_minutes
                # Only overwrite pen breakdown if we computed it (T1/T2)
                # For T3, breakdown dict is empty — leave existing values
                if breakdown:
                    existing.pen_2min = breakdown.get("2min", 0)
                    existing.pen_5min = breakdown.get("5min", 0)
                    existing.pen_10min = breakdown.get("10min", 0)
                    existing.pen_match = breakdown.get("match", 0)
                existing.computed_from_local = True
                existing.local_computed_at = now
                existing.last_updated = now
            updated += 1

        logger.info(
            "Local stats aggregation: %d PlayerStatistics rows upserted for season %s (tiers %s)",
            updated, season_id, sorted(tiers_set),
        )

    return updated
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd backend && .venv/bin/pytest tests/test_local_stats_aggregator.py -v
```
Expected: All tests PASS.

- [ ] **Step 5: Run full suite**

```bash
cd backend && .venv/bin/pytest --tb=short -q
```
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/local_stats_aggregator.py backend/tests/test_local_stats_aggregator.py
git commit -m "feat(stats): add local_stats_aggregator — aggregate PlayerStatistics from game data for T1-T3"
```

---

## Chunk 3: DataIndexer Integration

### Task 3: Add `compute_player_stats_for_season` to `DataIndexer` and gate T1–T3 in the API path

**Files:**
- Modify: `backend/app/services/data_indexer.py`

**Context:**
- `index_player_stats_for_season` is at line ~987. It has an `exact_tier` param.
- Add a guard at the top of `index_player_stats_for_season`: if `exact_tier in {1, 2, 3}`, log a skip message and return 0 (T1–T3 now handled by local aggregation).
- Add `compute_player_stats_for_season` as a thin wrapper that calls `aggregate_player_stats_for_season` with SyncStatus tracking (same pattern as other `index_*` methods).
- Import `aggregate_player_stats_for_season` from `app.services.local_stats_aggregator`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_local_stats_integration.py`:

```python
from unittest.mock import MagicMock
from contextlib import contextmanager
from app.services.data_indexer import DataIndexer


@pytest.fixture
def mock_db_with_engine(engine):
    db = MagicMock()
    @contextmanager
    def session_scope():
        with Session(engine) as s:
            yield s
            s.commit()
    db.session_scope = session_scope
    db.engine = engine
    return db


@pytest.fixture
def indexer(mock_db_with_engine):
    api = MagicMock()
    return DataIndexer(db=mock_db_with_engine, api=api)


def test_compute_player_stats_for_season_returns_int(engine, indexer):
    with Session(engine) as s:
        from app.models.db_models import Season, SyncStatus
        s.add(Season(id=1, text="2025"))
        s.commit()
    result = indexer.compute_player_stats_for_season(season_id=1)
    assert isinstance(result, int)


def test_index_player_stats_skips_tier_1(engine, indexer):
    """index_player_stats_for_season with exact_tier=1 should return 0 (T1 uses local computation)."""
    with Session(engine) as s:
        from app.models.db_models import Season
        s.add(Season(id=1, text="2025"))
        s.commit()
    result = indexer.index_player_stats_for_season(season_id=1, exact_tier=1)
    assert result == 0


def test_index_player_stats_skips_tier_3(engine, indexer):
    with Session(engine) as s:
        from app.models.db_models import Season
        s.add(Season(id=1, text="2025"))
        s.commit()
    result = indexer.index_player_stats_for_season(season_id=1, exact_tier=3)
    assert result == 0
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && .venv/bin/pytest tests/test_local_stats_integration.py::test_compute_player_stats_for_season_returns_int -v
```
Expected: FAIL — method doesn't exist yet.

- [ ] **Step 3: Add guard to `index_player_stats_for_season`**

At the very start of `index_player_stats_for_season`, after the `if exact_tier is not None:` block that sets `entity_type`, add:

```python
        # T1–T3 stats are now computed from local game data; skip API calls.
        if exact_tier in {1, 2, 3}:
            logger.info(
                "Skipping API player stats for tier %d (handled by local aggregation)", exact_tier
            )
            return 0
```

- [ ] **Step 4: Add `compute_player_stats_for_season` method**

After `index_player_stats_for_season` (around line 1100), add:

```python
    def compute_player_stats_for_season(
        self, season_id: int, force: bool = False, tiers: tuple[int, ...] = (1, 2, 3),
    ) -> int:
        """Compute PlayerStatistics from local GamePlayer/GameEvent data for T1–T3.

        Replaces per-player API calls for tiers where game data is complete.
        """
        entity_type = "compute_player_stats"
        entity_id = f"season:{season_id}"

        if not force and not self._should_update(entity_type, entity_id, max_age_hours=6):
            with self.db_service.session_scope() as _s:
                self._mark_sync_complete(_s, entity_type, entity_id, 0)
            return 0

        from app.services.local_stats_aggregator import aggregate_player_stats_for_season
        try:
            count = aggregate_player_stats_for_season(self.db_service, season_id, tiers=tiers)
            with self.db_service.session_scope() as session:
                self._mark_sync_complete(session, entity_type, entity_id, count)
            logger.info("compute_player_stats season=%s → %d rows", season_id, count)
            return count
        except Exception as exc:
            logger.error("compute_player_stats season=%s failed: %s", season_id, exc)
            raise
```

- [ ] **Step 5: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_local_stats_integration.py -v
```
Expected: All PASS.

- [ ] **Step 6: Run full suite**

```bash
cd backend && .venv/bin/pytest --tb=short -q
```
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/data_indexer.py backend/tests/test_local_stats_integration.py
git commit -m "feat(indexer): add compute_player_stats_for_season; skip API for T1-T3 in index_player_stats"
```

---

## Chunk 4: Scheduler + main.py

### Task 4: Add `compute_player_stats` scheduler policies and wire task in `main.py`

**Files:**
- Modify: `backend/app/services/scheduler.py`
- Modify: `backend/app/main.py`

**Context:**
- `POLICIES` list is at line ~61 in `scheduler.py`. Existing `player_stats_t1` policy is at line ~170.
- Pattern for a new policy (see `post_game_completion` at line ~155 as a model).
- In `main.py`, `_TASK_META` is at line ~1144; `_run()` handler is below it. Pattern: look at how `post_game_completion` task was wired — follow the same approach.
- Schedule: run `compute_player_stats` every 6 hours (same cadence as post_game_completion or use `max_age_hours=6`).
- `current_only: True` — only run for the current/highlighted season (same as `upcoming_games` policies).

- [ ] **Step 1: Write the test**

Add to `backend/tests/test_local_stats_integration.py`:

```python
def test_compute_player_stats_task_registered_in_main():
    """The task name must appear in _TASK_META so the scheduler can submit it."""
    from app.main import _TASK_META
    assert "compute_player_stats" in _TASK_META
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && .venv/bin/pytest tests/test_local_stats_integration.py::test_compute_player_stats_task_registered_in_main -v
```
Expected: FAIL.

- [ ] **Step 3: Add `compute_player_stats` policy to `scheduler.py`**

After the `post_game_completion` policy block (around line 165), add:

```python
    {
        "name":        "compute_player_stats",
        "entity_type": "compute_player_stats",
        "max_age_hours": 6,
        "task":        "compute_player_stats",
        "priority":    4,
        "scope":       "season",
        "current_only": True,
    },
```

- [ ] **Step 4: Wire `compute_player_stats` in `main.py`**

In `_TASK_META` dict, add:
```python
    "compute_player_stats": "Compute Player Stats (local)",
```

In `_TASK_LABELS` dict (if separate from META), add the same key.

In `_run()` handler, find the `if task in ("player_stats", ...)` block and add a parallel block:

```python
        if task == "compute_player_stats":
            n = await asyncio.to_thread(
                indexer.compute_player_stats_for_season,
                season,
                force,
            )
            stats["compute_player_stats"] = n
```

Also in `_TASK_COOLDOWNS` (line ~1177):
```python
    "compute_player_stats": 30,
```

- [ ] **Step 5: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_local_stats_integration.py -v
```
Expected: All PASS.

- [ ] **Step 6: Run full suite**

```bash
cd backend && .venv/bin/pytest --tb=short -q
```
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/scheduler.py backend/app/main.py backend/tests/test_local_stats_integration.py
git commit -m "feat(scheduler): add compute_player_stats policy (T1-T3, every 6h) and wire in main.py"
```

---

## Chunk 5: Admin Page

### Task 5: Add `/admin/unresolved-events` page

**Files:**
- Modify: `backend/app/main.py`
- Create: `backend/templates/admin_unresolved_events.html`
- Modify: `backend/locales/de/messages.json`, `en/messages.json`, `fr/messages.json`, `it/messages.json`
- Modify: `backend/templates/admin/_tab_database.html`

**Context:**
- `/admin/sync-failures` route at line ~3829 in `main.py` is the best model to follow.
- `admin_sync_failures.html` is the template to model after.
- Add a dismiss action: `POST /admin/unresolved-events/{id}/dismiss` — sets `resolved_at` + `resolved_by="dismissed"`.
- Link from `_tab_database.html` — already has the sync-failures button to model after (line 27).
- Import `UnresolvedPlayerEvent` in `main.py`.

- [ ] **Step 1: Write the test**

Add to `backend/tests/test_local_stats_integration.py`:

```python
def test_unresolved_events_page_returns_200(engine):
    """The /admin/unresolved-events route must exist and return HTML."""
    # Use the test client from conftest indirectly — just check route registration
    from app.main import app as fastapi_app
    routes = {r.path for r in fastapi_app.routes}
    assert "/admin/unresolved-events" in routes
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && .venv/bin/pytest tests/test_local_stats_integration.py::test_unresolved_events_page_returns_200 -v
```
Expected: FAIL.

- [ ] **Step 3: Add route in `main.py`**

Model after the `/admin/sync-failures` route. Add after that route:

```python
@app.get("/admin/unresolved-events", response_class=HTMLResponse)
async def admin_unresolved_events(request: Request, _: None = Depends(require_admin)):
    from app.models.db_models import UnresolvedPlayerEvent, Game, Team
    db = get_database_service()
    with db.session_scope() as session:
        rows = (
            session.query(UnresolvedPlayerEvent)
            .filter(UnresolvedPlayerEvent.resolved_at.is_(None))
            .order_by(UnresolvedPlayerEvent.created_at.desc())
            .limit(500)
            .all()
        )
        # Detach for template use
        data = [
            {
                "id": r.id,
                "game_id": r.game_id,
                "team_id": r.team_id,
                "raw_name": r.raw_name,
                "event_type": r.event_type,
                "created_at": r.created_at,
            }
            for r in rows
        ]
    locale = "de"
    t = get_translations(locale)
    return templates.TemplateResponse(
        "admin_unresolved_events.html",
        {"request": request, "locale": locale, "t": t, "rows": data},
    )


@app.post("/admin/unresolved-events/{event_id}/dismiss")
async def admin_dismiss_unresolved_event(
    event_id: int, request: Request, _: None = Depends(require_admin)
):
    from app.models.db_models import UnresolvedPlayerEvent
    from datetime import datetime, timezone
    db = get_database_service()
    try:
        with db.session_scope() as session:
            row = session.get(UnresolvedPlayerEvent, event_id)
            if row:
                row.resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
                row.resolved_by = "dismissed"
        return RedirectResponse("/admin/unresolved-events", status_code=303)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
```

- [ ] **Step 4: Create `admin_unresolved_events.html`**

Create `backend/templates/admin_unresolved_events.html` — model after `admin_sync_failures.html`. Show: raw_name, event_type, game_id, team_id, created_at, and a Dismiss button (POST form to `/admin/unresolved-events/{id}/dismiss`).

```html
{% extends "base.html" %}
{% block title %}Unresolved Player Events{% endblock %}
{% block content %}
<div class="container" style="max-width:900px;margin:2rem auto;padding:0 1rem">
  <h1 style="font-size:1.4rem;margin-bottom:1rem">⚠️ Unresolved Player Events</h1>
  <p style="font-size:.85rem;color:#8b949e;margin-bottom:1.5rem">
    These penalty events could not be matched to a player in the lineup.
    Stats for these events are excluded from PlayerStatistics until resolved or dismissed.
  </p>
  {% if rows %}
  <table style="width:100%;font-size:.82rem;border-collapse:collapse">
    <thead>
      <tr style="text-align:left;border-bottom:1px solid #30363d">
        <th style="padding:.4rem .6rem">Name in event</th>
        <th style="padding:.4rem .6rem">Event type</th>
        <th style="padding:.4rem .6rem">Game ID</th>
        <th style="padding:.4rem .6rem">Team ID</th>
        <th style="padding:.4rem .6rem">Created</th>
        <th style="padding:.4rem .6rem"></th>
      </tr>
    </thead>
    <tbody>
      {% for row in rows %}
      <tr style="border-bottom:1px solid #21262d">
        <td style="padding:.4rem .6rem">{{ row.raw_name }}</td>
        <td style="padding:.4rem .6rem">{{ row.event_type }}</td>
        <td style="padding:.4rem .6rem">{{ row.game_id }}</td>
        <td style="padding:.4rem .6rem">{{ row.team_id }}</td>
        <td style="padding:.4rem .6rem">{{ row.created_at.strftime('%Y-%m-%d') if row.created_at }}</td>
        <td style="padding:.4rem .6rem">
          <form method="post" action="/admin/unresolved-events/{{ row.id }}/dismiss">
            <button class="btn btn-sm">Dismiss</button>
          </form>
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p style="color:#8b949e">No unresolved events.</p>
  {% endif %}
  <div style="margin-top:1.5rem">
    <a href="/admin" class="btn btn-sm">← Back to Admin</a>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 5: Add link in `_tab_database.html`**

After the sync-failures link (line 27), add:

```html
              <a href="/admin/unresolved-events" class="btn btn-sm" style="text-decoration:none">🔗 Unresolved Events</a>
```

- [ ] **Step 6: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_local_stats_integration.py -v
```
Expected: All PASS.

- [ ] **Step 7: Run full suite**

```bash
cd backend && .venv/bin/pytest --tb=short -q
```
Expected: All pass.

- [ ] **Step 8: Commit**

```bash
git add backend/app/main.py backend/templates/admin_unresolved_events.html backend/templates/admin/_tab_database.html
git commit -m "feat(admin): add /admin/unresolved-events page with dismiss action"
```

---

## Chunk 6: Final Verification

### Task 6: Final check — linting + full test run

- [ ] **Step 1: Lint**

```bash
cd backend && .venv/bin/black app/ tests/ && .venv/bin/flake8 app/ tests/ --max-line-length=120 --count --select=E9,F63,F7,F82 --show-source
```
Expected: no errors.

- [ ] **Step 2: Full test suite with coverage**

```bash
cd backend && .venv/bin/pytest --tb=short -q --cov=app --cov-report=term-missing
```
Expected: All tests pass, no regressions.

- [ ] **Step 3: Commit (if any lint fixes needed)**

```bash
git add -u && git commit -m "chore: lint fixes for local player stats feature"
```
