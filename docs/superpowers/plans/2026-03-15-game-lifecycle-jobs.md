# Game Lifecycle Jobs Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace blind repeated polling of all game data with a lifecycle-aware system: upcoming games polled 3×/day for schedule changes, finished games polled until fully complete then frozen forever.

**Architecture:** A new `game_completeness.py` service holds tier-aware completeness rules and `_is_game_complete()`. Four new columns on `Game` track lifecycle state (`completeness_status`, `incomplete_fields`, `give_up_at`, `completeness_checked_at`). A new `GameSyncFailure` table logs abandoned games for admin review. Two new scheduler jobs (`upcoming_games` and `post_game_completion`) replace the existing `games`, `game_lineups`, and `game_events` policies.

**Tech Stack:** Python 3.12, SQLAlchemy 2.x, SQLite WAL, FastAPI, existing `DataIndexer` + `Scheduler` patterns.

**Spec:** `docs/superpowers/specs/2026-03-15-game-lifecycle-jobs-design.md`

---

## Chunk 1: Data Model + Migration

### Task 1: Add lifecycle columns to `Game` and create `GameSyncFailure`

**Files:**
- Modify: `backend/app/models/db_models.py`
- Test: `backend/tests/test_game_lifecycle_model.py`

- [ ] **Step 1: Write a failing test asserting the new columns exist**

```python
# backend/tests/test_game_lifecycle_model.py
import pytest
from sqlalchemy import text
from app.models.db_models import Game, GameSyncFailure


def test_game_has_completeness_columns(app):
    from app.services.database import get_db_service
    db = get_db_service()
    with db.engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(games)"))}
    assert "completeness_status" in cols
    assert "incomplete_fields" in cols
    assert "give_up_at" in cols
    assert "completeness_checked_at" in cols


def test_game_sync_failure_table_exists(app):
    from app.services.database import get_db_service
    db = get_db_service()
    with db.engine.connect() as conn:
        tables = {row[0] for row in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        )}
    assert "game_sync_failures" in tables


def test_game_completeness_status_defaults_to_upcoming(app):
    """Uses conftest-seeded season/team data; see conftest.py for IDs."""
    from app.services.database import get_db_service
    from app.models.db_models import Game, Season, Team
    db = get_db_service()
    # Confirm season + teams exist before inserting Game (FK constraints active)
    with db.session_scope() as session:
        season = session.query(Season).first()
        assert season is not None, "conftest must seed at least one Season"
        team_ids = [t.id for t in session.query(Team).limit(2).all()]
        assert len(team_ids) >= 2, "conftest must seed at least two Teams"
        game = Game(
            id=99999, season_id=season.id,
            home_team_id=team_ids[0], away_team_id=team_ids[1],
        )
        session.add(game)
    with db.session_scope() as session:
        g = session.query(Game).filter_by(id=99999).first()
        assert g.completeness_status == "upcoming"
        assert g.incomplete_fields is None
        assert g.give_up_at is None
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd backend && .venv/bin/pytest tests/test_game_lifecycle_model.py -v
```
Expected: `FAILED` — columns don't exist yet.

- [ ] **Step 3: Add new columns to `Game` and `GameSyncFailure` table to `db_models.py`**

In `backend/app/models/db_models.py`, after `last_events_update` (line 208), add to the `Game` class:

```python
# Lifecycle columns (added for game lifecycle jobs refactor)
completeness_status: Mapped[str] = mapped_column(
    String(20), nullable=False, default="upcoming", server_default="upcoming"
)
incomplete_fields: Mapped[Optional[list]] = mapped_column(
    JSON, nullable=True  # list of missing field name strings, e.g. ["events", "lineup"]
)
give_up_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
completeness_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
```

Make sure `JSON` is imported at the top of `db_models.py` alongside the other SQLAlchemy column types (it is already used by `GameEvent.raw_data` — confirm it is present).

After the `Game` table args (existing indexes), add the new index:

```python
Index('idx_game_completeness_status', 'completeness_status'),
```

After the `GameEvent` class, add the new table:

```python
class GameSyncFailure(Base):
    """Records games that were abandoned before reaching full completeness."""
    __tablename__ = "game_sync_failures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(Integer, ForeignKey("games.id"), nullable=False)
    season_id: Mapped[int] = mapped_column(Integer, nullable=False)  # denormalized, no FK
    abandoned_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    missing_fields: Mapped[Optional[list]] = mapped_column(
        JSON, nullable=True  # list of missing field name strings
    )
    can_retry: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    retried_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index('idx_gsf_game_id', 'game_id'),
        Index('idx_gsf_season_id', 'season_id'),
        Index('idx_gsf_can_retry', 'can_retry'),
    )
```

Make sure `GameSyncFailure` is imported wherever `Game` is imported from `db_models`.

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd backend && .venv/bin/pytest tests/test_game_lifecycle_model.py -v
```
Expected: `PASSED` (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/db_models.py backend/tests/test_game_lifecycle_model.py
git commit -m "feat(model): add Game lifecycle columns and GameSyncFailure table"
```

---

### Task 2: Add idempotent DB migration + startup backfill

**Files:**
- Modify: `backend/app/services/database.py`
- Test: `backend/tests/test_game_lifecycle_model.py` (extend)

The migration runs in `_run_sqlite_migrations()`. It must:
1. ADD COLUMN all four new Game columns (if absent)
2. CREATE TABLE `game_sync_failures` (if absent)
3. CREATE INDEX `idx_game_completeness_status` (if absent)
4. Backfill `completeness_status` for existing finished games (one-time)

- [ ] **Step 1: Write failing tests for migration backfill logic**

Add to `backend/tests/test_game_lifecycle_model.py`:

```python
```python
# Add these imports at top of test_game_lifecycle_model.py
from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from app.models.db_models import Game, GameSyncFailure, GameEvent, Season, Team
```

```python
def _null_out_status(db, game_id: int):
    """Helper: reset completeness_status to NULL to simulate pre-migration state."""
    with db.engine.connect() as conn:
        conn.execute(text(
            f"UPDATE games SET completeness_status = NULL WHERE id = {game_id}"
        ))
        conn.commit()


def _get_valid_season_and_teams(session):
    """Return (season_id, home_team_id, away_team_id) from conftest-seeded data."""
    season = session.query(Season).first()
    assert season is not None, "conftest must seed at least one Season"
    teams = session.query(Team).limit(2).all()
    assert len(teams) >= 2, "conftest must seed at least two Teams"
    return season.id, teams[0].id, teams[1].id


def test_migration_sets_upcoming_for_scheduled_games(app):
    """Scheduled games get completeness_status = 'upcoming'."""
    from app.services.database import get_db_service
    db = get_db_service()
    with db.session_scope() as session:
        sid, h, a = _get_valid_season_and_teams(session)
        game = Game(id=99990, season_id=sid, home_team_id=h, away_team_id=a,
                    status="scheduled")
        session.add(game)
    _null_out_status(db, 99990)
    db._backfill_completeness_status()
    with db.session_scope() as session:
        g = session.query(Game).filter_by(id=99990).first()
        assert g.completeness_status == "upcoming"


def test_migration_sets_complete_for_finished_games_with_score_and_events(app):
    """Finished games with score + at least one non-best-player event → 'complete'."""
    from app.services.database import get_db_service
    db = get_db_service()
    past = datetime.now(timezone.utc) - timedelta(days=10)
    with db.session_scope() as session:
        sid, h, a = _get_valid_season_and_teams(session)
        game = Game(id=99991, season_id=sid, home_team_id=h, away_team_id=a,
                    status="finished", home_score=3, away_score=2, game_date=past)
        session.add(game)
        session.flush()
        event = GameEvent(game_id=99991, event_type="goal", period="1st",
                          season_id=sid, team_id=h)
        session.add(event)
    _null_out_status(db, 99991)
    db._backfill_completeness_status()
    with db.session_scope() as session:
        g = session.query(Game).filter_by(id=99991).first()
        assert g.completeness_status == "complete"


def test_migration_sets_post_game_for_recent_finished_games_without_events(app):
    """Recent finished games (game_date + 3d > now) with no events → 'post_game'."""
    from app.services.database import get_db_service
    db = get_db_service()
    recent = datetime.now(timezone.utc) - timedelta(hours=12)
    with db.session_scope() as session:
        sid, h, a = _get_valid_season_and_teams(session)
        game = Game(id=99993, season_id=sid, home_team_id=h, away_team_id=a,
                    status="finished", home_score=2, away_score=0, game_date=recent)
        session.add(game)
    _null_out_status(db, 99993)
    db._backfill_completeness_status()
    with db.session_scope() as session:
        g = session.query(Game).filter_by(id=99993).first()
        assert g.completeness_status == "post_game"
        assert g.give_up_at is not None


def test_migration_sets_abandoned_for_old_finished_games_without_events(app):
    """Old finished games (game_date + 3d < now) with no events → 'abandoned'."""
    from app.services.database import get_db_service
    db = get_db_service()
    old_date = datetime.now(timezone.utc) - timedelta(days=10)
    with db.session_scope() as session:
        sid, h, a = _get_valid_season_and_teams(session)
        game = Game(id=99992, season_id=sid, home_team_id=h, away_team_id=a,
                    status="finished", home_score=2, away_score=1, game_date=old_date)
        session.add(game)
    _null_out_status(db, 99992)
    db._backfill_completeness_status()
    with db.session_scope() as session:
        g = session.query(Game).filter_by(id=99992).first()
        assert g.completeness_status == "abandoned"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && .venv/bin/pytest tests/test_game_lifecycle_model.py::test_migration_sets_upcoming_for_scheduled_games -v
```
Expected: `FAILED` — `_backfill_completeness_status` doesn't exist.

- [ ] **Step 3: Add migration SQL + `_backfill_completeness_status()` to `database.py`**

Inside `_run_sqlite_migrations()` (after the existing migrations block), add:

```python
# --- Game lifecycle columns ---
game_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(games)"))}
if "completeness_status" not in game_cols:
    conn.execute(text(
        "ALTER TABLE games ADD COLUMN completeness_status TEXT NOT NULL DEFAULT 'upcoming'"
    ))
if "incomplete_fields" not in game_cols:
    conn.execute(text("ALTER TABLE games ADD COLUMN incomplete_fields TEXT"))
if "give_up_at" not in game_cols:
    conn.execute(text("ALTER TABLE games ADD COLUMN give_up_at TIMESTAMP"))
if "completeness_checked_at" not in game_cols:
    conn.execute(text("ALTER TABLE games ADD COLUMN completeness_checked_at TIMESTAMP"))

# --- GameSyncFailure table ---
conn.execute(text("""
    CREATE TABLE IF NOT EXISTS game_sync_failures (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id INTEGER NOT NULL REFERENCES games(id),
        season_id INTEGER NOT NULL,
        abandoned_at TIMESTAMP NOT NULL,
        missing_fields TEXT,
        can_retry INTEGER NOT NULL DEFAULT 0,
        retried_at TIMESTAMP
    )
"""))
conn.execute(text(
    "CREATE INDEX IF NOT EXISTS idx_gsf_game_id ON game_sync_failures(game_id)"
))
conn.execute(text(
    "CREATE INDEX IF NOT EXISTS idx_gsf_season_id ON game_sync_failures(season_id)"
))
conn.execute(text(
    "CREATE INDEX IF NOT EXISTS idx_gsf_can_retry ON game_sync_failures(can_retry)"
))
conn.execute(text(
    "CREATE INDEX IF NOT EXISTS idx_game_completeness_status "
    "ON games(completeness_status)"
))
conn.commit()
```

Then add the `_backfill_completeness_status()` method to `DatabaseService` (call it at the end of `_run_sqlite_migrations`):

```python
def _backfill_completeness_status(self):
    """Idempotent: set completeness_status for rows where it is NULL.

    Rules (applied in Python after a single DB query):
    - status != 'finished' (or NULL)                     → 'upcoming'
    - status == 'finished' + has ≥1 GameEvent            → 'complete'
    - status == 'finished' + no events + deadline future → 'post_game'
    - status == 'finished' + no events + deadline past   → 'abandoned'
    """
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import text

    now = datetime.now(timezone.utc)

    with self.engine.connect() as conn:
        # Set upcoming for non-finished NULL rows
        conn.execute(text("""
            UPDATE games
            SET completeness_status = 'upcoming'
            WHERE completeness_status IS NULL
              AND (status IS NULL OR status != 'finished')
        """))

        # Finished + has score + has ≥1 non-best-player event → complete
        # Conservative: lower-tier games without events will fall to post_game/abandoned
        # and be revisited by the post_game_completion job.
        conn.execute(text("""
            UPDATE games
            SET completeness_status = 'complete'
            WHERE completeness_status IS NULL
              AND status = 'finished'
              AND home_score IS NOT NULL
              AND away_score IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM game_events ge
                  WHERE ge.game_id = games.id
                    AND ge.event_type != 'best_player'
              )
        """))

        # Finished + incomplete + known game_date + deadline in future → post_game
        conn.execute(text("""
            UPDATE games
            SET completeness_status = 'post_game',
                give_up_at = datetime(game_date, '+3 days')
            WHERE completeness_status IS NULL
              AND status = 'finished'
              AND game_date IS NOT NULL
              AND datetime(game_date, '+3 days') > :now
        """), {"now": now.isoformat()})

        # Finished + NULL game_date → post_game with generous fixed deadline
        conn.execute(text("""
            UPDATE games
            SET completeness_status = 'post_game',
                give_up_at = :future
            WHERE completeness_status IS NULL
              AND status = 'finished'
              AND game_date IS NULL
        """), {"future": (now + timedelta(days=3)).isoformat()})

        # Finished + incomplete + deadline past → abandoned
        conn.execute(text("""
            UPDATE games
            SET completeness_status = 'abandoned'
            WHERE completeness_status IS NULL
              AND status = 'finished'
        """))

        conn.commit()
```

Call `self._backfill_completeness_status()` at the very end of `_run_sqlite_migrations()`.

- [ ] **Step 4: Run all migration tests**

```bash
cd backend && .venv/bin/pytest tests/test_game_lifecycle_model.py -v
```
Expected: all `PASSED`.

- [ ] **Step 5: Run full test suite to check no regressions**

```bash
cd backend && .venv/bin/pytest tests/ -v --tb=short 2>&1 | tail -30
```
Expected: all existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/database.py backend/tests/test_game_lifecycle_model.py
git commit -m "feat(db): add idempotent migration for game lifecycle columns and GameSyncFailure table"
```

---

## Chunk 2: Completeness Service

### Task 3: Create `game_completeness.py`

**Files:**
- Create: `backend/app/services/game_completeness.py`
- Test: `backend/tests/test_game_completeness.py`

- [ ] **Step 1: Write failing tests for `_is_game_complete` and `_resolve_game_tier`**

```python
# backend/tests/test_game_completeness.py
import json
import pytest
from unittest.mock import MagicMock, patch
from app.services.game_completeness import (
    TIER_COMPLETENESS_FIELDS,
    _resolve_game_tier,
    _is_game_complete,
)
from app.models.db_models import Game, GameEvent, GamePlayer


# --- Helpers ---

def _make_game(**kwargs):
    defaults = dict(
        id=1, season_id=1, home_team_id=10, away_team_id=20,
        status="finished", home_score=3, away_score=1,
        referee_1="Ref One", spectators=500,
        completeness_status="post_game",
    )
    defaults.update(kwargs)
    g = Game.__new__(Game)
    for k, v in defaults.items():
        setattr(g, k, v)
    return g


def _make_session(event_count=1, player_count=1, best_player_count=2):
    """Build a mock session that returns distinct counts per query type.

    - GameEvent + filter (event_type != best_player) → event_count
    - GameEvent + filter_by(event_type="best_player") → best_player_count
    - GamePlayer + filter_by → player_count

    event_count and best_player_count are kept separate so tests can verify
    that the events check and the best_players check exercise different paths.
    """
    session = MagicMock()

    def query_side_effect(model):
        q = MagicMock()
        if model is GameEvent:
            def filter_by_fn(**kw):
                fq = MagicMock()
                # Only best_player filter_by uses best_player_count
                if kw.get("event_type") == "best_player":
                    fq.count.return_value = best_player_count
                else:
                    fq.count.return_value = event_count
                return fq
            q.filter_by = filter_by_fn

            def filter_fn(*args):
                # Column-expression filter used for events (event_type != best_player)
                fq = MagicMock()
                fq.count.return_value = event_count
                return fq
            q.filter = filter_fn
        elif model is GamePlayer:
            def filter_by_fn(**kw):
                fq = MagicMock()
                fq.count.return_value = player_count
                return fq
            q.filter_by = filter_by_fn
        return q

    session.query = query_side_effect
    return session


# --- TIER_COMPLETENESS_FIELDS ---

def test_tier1_requires_all_fields():
    assert TIER_COMPLETENESS_FIELDS[1] == {
        "score", "referees", "spectators", "events", "lineup", "best_players"
    }


def test_tier3_requires_only_score():
    assert TIER_COMPLETENESS_FIELDS[3] == {"score"}


# --- _resolve_game_tier ---

def test_resolve_tier_returns_1_for_nla_game():
    game = _make_game(group_id=5)
    session = MagicMock()
    # SA 2.x: session.get(LeagueGroup, game.group_id) — mock via session.get
    from app.models.db_models import LeagueGroup, League
    mock_group = MagicMock(spec=LeagueGroup)
    mock_league_obj = MagicMock(spec=League)
    mock_league_obj.league_id = 24  # NLA → tier 1
    mock_group.league = mock_league_obj
    session.get.return_value = mock_group

    tier = _resolve_game_tier(game, session)
    assert tier == 1
    session.get.assert_called_once_with(LeagueGroup, 5)


def test_resolve_tier_fallback_to_6_when_group_id_is_none():
    game = _make_game(group_id=None)
    session = MagicMock()
    tier = _resolve_game_tier(game, session)
    assert tier == 6
    session.get.assert_not_called()  # short-circuits before any DB call


def test_resolve_tier_fallback_to_6_when_league_unknown():
    game = _make_game(group_id=99)
    session = MagicMock()
    mock_group = MagicMock()
    mock_league_obj = MagicMock()
    mock_league_obj.league_id = 9999  # not in _LEAGUE_TIERS
    mock_group.league = mock_league_obj
    session.get.return_value = mock_group
    tier = _resolve_game_tier(game, session)
    assert tier == 6


# --- _is_game_complete ---

def test_complete_tier1_game_with_all_fields():
    game = _make_game()
    session = _make_session(event_count=5, player_count=12, best_player_count=2)
    is_complete, missing = _is_game_complete(game, tier=1, session=session)
    assert is_complete is True
    assert missing == []


def test_missing_score_returns_score_in_missing():
    game = _make_game(home_score=None)
    session = _make_session()
    is_complete, missing = _is_game_complete(game, tier=1, session=session)
    assert is_complete is False
    assert "score" in missing


def test_missing_referee_returns_referees_in_missing():
    game = _make_game(referee_1=None)
    session = _make_session()
    is_complete, missing = _is_game_complete(game, tier=1, session=session)
    assert is_complete is False
    assert "referees" in missing


def test_missing_events_returns_events_in_missing():
    game = _make_game()
    session = _make_session(event_count=0)
    is_complete, missing = _is_game_complete(game, tier=1, session=session)
    assert is_complete is False
    assert "events" in missing


def test_missing_best_players_returns_best_players_in_missing():
    game = _make_game()
    session = _make_session(best_player_count=0)
    is_complete, missing = _is_game_complete(game, tier=1, session=session)
    assert is_complete is False
    assert "best_players" in missing


def test_tier3_complete_with_score_only():
    """Tier 3 only requires score — events/lineup not checked."""
    game = _make_game(referee_1=None, spectators=None)
    session = _make_session(event_count=0, player_count=0)
    is_complete, missing = _is_game_complete(game, tier=3, session=session)
    assert is_complete is True
    assert missing == []


def test_unknown_tier_falls_back_to_score_only():
    game = _make_game(referee_1=None, spectators=None)
    session = _make_session(event_count=0, player_count=0)
    is_complete, missing = _is_game_complete(game, tier=99, session=session)
    assert is_complete is True


def test_events_and_best_players_are_checked_independently():
    """Verify events and best_players paths are distinct: having best_players
    but zero real events should still report 'events' as missing."""
    game = _make_game()
    # 0 regular events, 2 best_player events
    session = _make_session(event_count=0, best_player_count=2)
    is_complete, missing = _is_game_complete(game, tier=1, session=session)
    assert is_complete is False
    assert "events" in missing
    assert "best_players" not in missing
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && .venv/bin/pytest tests/test_game_completeness.py -v 2>&1 | head -20
```
Expected: `ImportError` — module doesn't exist yet.

- [ ] **Step 3: Create `backend/app/services/game_completeness.py`**

```python
"""Game completeness: tier-aware rules for when a finished game is fully indexed."""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.models.db_models import GameEvent, GamePlayer, LeagueGroup

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from app.models.db_models import Game

# Keyed by tier (1–6). Update empirically as each league's API coverage is confirmed.
TIER_COMPLETENESS_FIELDS: dict[int, set[str]] = {
    1: {"score", "referees", "spectators", "events", "lineup", "best_players"},
    2: {"score", "referees", "spectators", "events", "lineup", "best_players"},
    3: {"score"},  # to be confirmed by testing
    4: {"score"},  # to be confirmed by testing
    5: {"score"},  # to be confirmed by testing
    6: {"score"},  # to be confirmed by testing
}
_DEFAULT_FIELDS = {"score"}

# Mirrors LEAGUE_TIERS from data_indexer to avoid circular imports
_LEAGUE_TIERS: dict[int, int] = {
    1: 1, 10: 1, 24: 1,
    2: 2, 13: 2,
    3: 3, 14: 3,
    4: 4, 15: 4,
    5: 5, 16: 5,
    6: 6, 7: 6, 12: 6, 23: 6, 25: 6,
}


def _resolve_game_tier(game: "Game", session: "Session") -> int:
    """Resolve the league tier for a game.

    Chain: Game.group_id → LeagueGroup → League.league_id → tier.
    Returns 6 (most conservative) on any lookup failure or NULL group_id.

    Note: _LEAGUE_TIERS is a local copy of data_indexer.LEAGUE_TIERS (minus tier 7
    sentinel). Keep in sync when adding new league IDs to the indexer.
    """
    if game.group_id is None:
        return 6
    # SA 2.x: use session.get() not session.query().get()
    group = session.get(LeagueGroup, game.group_id)
    if group is None or group.league is None:
        return 6
    return _LEAGUE_TIERS.get(group.league.league_id, 6)


def _is_game_complete(
    game: "Game", tier: int, session: "Session"
) -> tuple[bool, list[str]]:
    """Check whether a finished game has all required fields for its tier.

    Returns (is_complete, missing_fields).
    Only fields in TIER_COMPLETENESS_FIELDS[tier] are checked.
    Unknown tiers fall back to {"score"}.
    """
    required = TIER_COMPLETENESS_FIELDS.get(tier, _DEFAULT_FIELDS)
    missing: list[str] = []

    if "score" in required:
        if game.home_score is None or game.away_score is None:
            missing.append("score")

    if "referees" in required:
        if game.referee_1 is None:
            missing.append("referees")

    if "spectators" in required:
        if game.spectators is None:
            missing.append("spectators")

    if "events" in required:
        count = (
            session.query(GameEvent)
            .filter(
                GameEvent.game_id == game.id,
                GameEvent.event_type != "best_player",
            )
            .count()
        )
        if count == 0:
            missing.append("events")

    if "lineup" in required:
        count = (
            session.query(GamePlayer)
            .filter_by(game_id=game.id)
            .count()
        )
        if count == 0:
            missing.append("lineup")

    if "best_players" in required:
        count = (
            session.query(GameEvent)
            .filter_by(game_id=game.id, event_type="best_player")
            .count()
        )
        if count == 0:
            missing.append("best_players")

    return (len(missing) == 0, missing)
```

- [ ] **Step 4: Run completeness tests**

```bash
cd backend && .venv/bin/pytest tests/test_game_completeness.py -v
```
Expected: all `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/game_completeness.py backend/tests/test_game_completeness.py
git commit -m "feat(completeness): add tier-aware game completeness service"
```

---

## Chunk 3: New Indexer Methods

### Task 4: Add `index_upcoming_games(season_id)` to `DataIndexer`

**Files:**
- Modify: `backend/app/services/data_indexer.py`
- Test: `backend/tests/test_game_lifecycle_indexer.py`

This method reuses the existing `index_games_for_league` (which already updates game metadata) and afterwards flips any games that have become `finished` from `upcoming` → `post_game`.

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_game_lifecycle_indexer.py
import json
import pytest
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, call

from app.services.data_indexer import DataIndexer
from app.models.db_models import Game


def _make_indexer():
    indexer = DataIndexer.__new__(DataIndexer)
    indexer.client = MagicMock()
    indexer.db_service = MagicMock()
    indexer._logger = MagicMock()
    return indexer


def _session_ctx(session):
    @contextmanager
    def _scope():
        yield session
    return _scope


def test_index_upcoming_games_flips_finished_game_to_post_game(app):
    """A game that the API now returns as 'finished' gets completeness_status=post_game."""
    from app.services.database import get_db_service
    from app.models.db_models import Season, League, LeagueGroup

    db = get_db_service()
    now = datetime.now(timezone.utc)

    with db.session_scope() as session:
        # Minimal season/league/group/game setup
        season = session.query(Season).first()
        if not season:
            season = Season(id=2025, text="2024/25", highlighted=True)
            session.add(season)
            session.flush()

        game = Game(
            id=88881, season_id=season.id,
            home_team_id=1, away_team_id=2,
            status="scheduled",
            game_date=now - timedelta(hours=3),
            completeness_status="upcoming",
        )
        session.add(game)

    # Mock index_games_for_league to simulate the API now returning this game as finished
    def fake_update_game_status(*args, **kwargs):
        with db.session_scope() as s:
            g = s.query(Game).filter_by(id=88881).first()
            if g:
                g.status = "finished"
                g.home_score = 3
                g.away_score = 1
        return 1

    indexer = _make_indexer()
    indexer.db_service = db

    with patch.object(indexer, "index_games_for_league", side_effect=fake_update_game_status):
        with patch.object(indexer, "_get_league_groups_for_season", return_value=[
            {"league_db_id": 1, "season_id": season.id, "league_id": 24,
             "game_class": 1, "group_name": "Regelsaison", "group_db_id": 1}
        ]):
            indexer.index_upcoming_games(season.id)

    with db.session_scope() as session:
        g = session.query(Game).filter_by(id=88881).first()
        assert g.completeness_status == "post_game"
        assert g.give_up_at is not None
        assert g.give_up_at > now


def test_index_upcoming_games_does_not_flip_complete_games(app):
    """Complete games are not flipped to post_game even if their API status returns 'finished'."""
    from app.services.database import get_db_service
    db = get_db_service()
    now = datetime.now(timezone.utc)

    with db.session_scope() as session:
        season = session.query(Season).first()
        teams = session.query(Team).limit(2).all()
        game = Game(
            id=88882, season_id=season.id,
            home_team_id=teams[0].id, away_team_id=teams[1].id,
            status="finished",
            completeness_status="complete",
            home_score=2, away_score=0,
        )
        session.add(game)

    indexer = _make_indexer()
    indexer.db_service = db

    def fake_update(*args, **kwargs):
        # Simulate API returning status=finished — but game is already complete
        return 0

    # Return a real group pointing to the season so the post-flip check runs
    with patch.object(indexer, "index_games_for_league", side_effect=fake_update):
        with patch.object(indexer, "_get_league_groups_for_season", return_value=[
            {"league_db_id": 1, "season_id": season.id, "league_id": 24,
             "game_class": 1, "group_name": "Reg", "group_db_id": None}
        ]):
            indexer.index_upcoming_games(season.id)

    # The post-group flip logic only affects games with completeness_status == 'upcoming'
    with db.session_scope() as session:
        g = session.query(Game).filter_by(id=88882).first()
        assert g.completeness_status == "complete", (
            "A complete game must never be demoted by the upcoming_games job"
        )
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && .venv/bin/pytest tests/test_game_lifecycle_indexer.py -v 2>&1 | head -20
```
Expected: `AttributeError` — `index_upcoming_games` doesn't exist.

- [ ] **Step 3: Add `index_upcoming_games` to `DataIndexer` (append near existing `index_games_for_league`)**

In `data_indexer.py`, add after `index_games_for_league`:

```python
def index_upcoming_games(self, season_id: int) -> int:
    """Poll upcoming/live games for schedule updates (3× per day job).

    Reuses index_games_for_league to refresh game metadata (date, time,
    venue, referees). After each group refresh, transitions any games
    that the API has flipped to 'finished' from 'upcoming' → 'post_game'.

    Returns: total games transitioned to post_game.
    """
    from datetime import timedelta
    from app.models.db_models import Game

    groups = self._get_league_groups_for_season(season_id)
    transitioned = 0

    for group in groups:
        try:
            self.index_games_for_league(
                league_db_id=group["league_db_id"],
                season_id=season_id,
                league_id=group["league_id"],
                game_class=group["game_class"],
                group_name=group.get("group_name"),
                group_db_id=group.get("group_db_id"),
            )
        except Exception as exc:
            self._logger.warning(
                "index_upcoming_games: group %s failed: %s",
                group.get("group_name"), exc,
            )
            continue

        # Flip any finished games that are still marked 'upcoming' or 'live'
        try:
            with self.db_service.session_scope() as session:
                games = (
                    session.query(Game)
                    .filter(
                        Game.season_id == season_id,
                        Game.status == "finished",
                        Game.completeness_status == "upcoming",
                        Game.group_id == group.get("group_db_id"),
                    )
                    .all()
                )
                now = _utcnow()
                for game in games:
                    game.completeness_status = "post_game"
                    game.give_up_at = (
                        game.game_date + timedelta(days=3)
                        if game.game_date
                        else now + timedelta(days=3)
                    )
                    game.incomplete_fields = None  # will be set by post_game job
                    transitioned += 1
        except Exception as exc:
            self._logger.warning(
                "index_upcoming_games: post-group transition failed: %s", exc
            )

    return transitioned
```

Also add `_utcnow` to the import at the top of `data_indexer.py` (line 17–19). Change:
```python
from app.models.db_models import (
    Season, Club, Team, Player, TeamPlayer, League, LeagueGroup,
    Game, GamePlayer, GameEvent, PlayerStatistics, SyncStatus
)
```
to:
```python
from app.models.db_models import (
    Season, Club, Team, Player, TeamPlayer, League, LeagueGroup,
    Game, GamePlayer, GameEvent, PlayerStatistics, SyncStatus, _utcnow,
)
```

Also add `_get_league_groups_for_season` as a private helper on `DataIndexer` (add near the other private helpers). This method does NOT exist in the codebase — implement it following the `index_leagues_path` pattern at lines ~2120–2154:

```python
def _get_league_groups_for_season(self, season_id: int) -> list[dict]:
    """Return all (league, group) combinations for a season.

    Each dict has the keys needed by index_games_for_league:
      league_db_id, season_id, league_id, game_class, group_name, group_db_id
    """
    result = []
    with self.db_service.session_scope() as session:
        leagues = session.query(League).filter(
            League.season_id == season_id
        ).all()
        league_rows = [
            (lg.id, lg.league_id, lg.game_class) for lg in leagues
        ]

    for league_db_id, league_id, game_class in league_rows:
        with self.db_service.session_scope() as session:
            groups = session.query(LeagueGroup).filter(
                LeagueGroup.league_id == league_db_id
            ).all()
            group_rows = [(g.id, g.name) for g in groups] or [(None, None)]

        for grp_db_id, grp_name in group_rows:
            result.append({
                "league_db_id": league_db_id,
                "season_id": season_id,
                "league_id": league_id,
                "game_class": game_class,
                "group_name": grp_name,
                "group_db_id": grp_db_id,
            })
    return result
```

- [ ] **Step 4: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_game_lifecycle_indexer.py::test_index_upcoming_games_flips_finished_game_to_post_game tests/test_game_lifecycle_indexer.py::test_index_upcoming_games_skips_complete_games -v
```
Expected: both `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/data_indexer.py backend/tests/test_game_lifecycle_indexer.py
git commit -m "feat(indexer): add index_upcoming_games method"
```

---

### Task 5: Add `index_post_game_completion(season_id)` to `DataIndexer`

**Files:**
- Modify: `backend/app/services/data_indexer.py`
- Modify: `backend/tests/test_game_lifecycle_indexer.py`

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/test_game_lifecycle_indexer.py`:

```python
def test_post_game_completion_marks_complete_when_all_fields_present(app):
    """A post_game game that passes completeness check gets marked complete."""
    from app.services.database import get_db_service
    from app.models.db_models import GameEvent, GamePlayer
    from datetime import timedelta

    db = get_db_service()
    now = datetime.now(timezone.utc)

    with db.session_scope() as session:
        season = session.query(Season).first()
        game = Game(
            id=88883, season_id=season.id,
            home_team_id=1, away_team_id=2,
            status="finished",
            home_score=2, away_score=1,
            referee_1="Ref A", spectators=300,
            completeness_status="post_game",
            game_date=now - timedelta(hours=5),
            give_up_at=now + timedelta(days=2),
        )
        session.add(game)
        # Add the minimum required data for tier 6 (score already set above)
        session.flush()

    indexer = _make_indexer()
    indexer.db_service = db

    # Mock index_game_events and index_game_lineup to be no-ops (data already there)
    with patch.object(indexer, "index_game_events", return_value=0):
        with patch.object(indexer, "index_game_lineup", return_value=0):
            with patch("app.services.data_indexer.TIER_COMPLETENESS_FIELDS",
                       {1: {"score"}, 2: {"score"}, 3: {"score"},
                        4: {"score"}, 5: {"score"}, 6: {"score"}}):
                indexer.index_post_game_completion(season.id)

    with db.session_scope() as session:
        g = session.query(Game).filter_by(id=88883).first()
        assert g.completeness_status == "complete"
        assert g.incomplete_fields is None
        assert g.completeness_checked_at is not None


def test_post_game_completion_abandons_past_deadline_game(app):
    """A post_game game past give_up_at gets abandoned + GameSyncFailure written."""
    from app.services.database import get_db_service
    from app.models.db_models import GameSyncFailure
    from datetime import timedelta

    db = get_db_service()
    now = datetime.now(timezone.utc)

    with db.session_scope() as session:
        season = session.query(Season).first()
        game = Game(
            id=88884, season_id=season.id,
            home_team_id=1, away_team_id=2,
            status="finished",
            home_score=None,  # missing score → not complete
            completeness_status="post_game",
            game_date=now - timedelta(days=5),
            give_up_at=now - timedelta(hours=1),  # past deadline
        )
        session.add(game)

    indexer = _make_indexer()
    indexer.db_service = db

    with patch.object(indexer, "index_game_events", return_value=0):
        with patch.object(indexer, "index_game_lineup", return_value=0):
            indexer.index_post_game_completion(season.id)

    with db.session_scope() as session:
        g = session.query(Game).filter_by(id=88884).first()
        assert g.completeness_status == "abandoned"
        failure = session.query(GameSyncFailure).filter_by(game_id=88884).first()
        assert failure is not None
        assert failure.can_retry is False or failure.can_retry == 0


def test_manual_retry_resets_game_to_post_game(app):
    """Setting can_retry=True on a GameSyncFailure resets the game to post_game."""
    from app.services.database import get_db_service
    from app.models.db_models import GameSyncFailure
    from datetime import timedelta

    db = get_db_service()
    now = datetime.now(timezone.utc)

    with db.session_scope() as session:
        season = session.query(Season).first()
        game = Game(
            id=88885, season_id=season.id,
            home_team_id=1, away_team_id=2,
            status="finished", home_score=None,
            completeness_status="abandoned",
            game_date=now - timedelta(days=5),
            give_up_at=now - timedelta(hours=1),
        )
        session.add(game)
        failure = GameSyncFailure(
            game_id=88885, season_id=season.id,
            abandoned_at=now - timedelta(hours=1),
            missing_fields=["score"],  # JSON column: assign list directly
            can_retry=True,
        )
        session.add(failure)

    indexer = _make_indexer()
    indexer.db_service = db

    with patch.object(indexer, "index_game_events", return_value=0):
        with patch.object(indexer, "index_game_lineup", return_value=0):
            indexer.index_post_game_completion(season.id)

    with db.session_scope() as session:
        g = session.query(Game).filter_by(id=88885).first()
        # Should have been reset to post_game (new give_up_at in future)
        assert g.completeness_status in ("post_game", "abandoned", "complete")
        failure = session.query(GameSyncFailure).filter_by(game_id=88885).first()
        assert failure.retried_at is not None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && .venv/bin/pytest tests/test_game_lifecycle_indexer.py -k "post_game" -v 2>&1 | head -20
```
Expected: `AttributeError` — `index_post_game_completion` doesn't exist.

- [ ] **Step 3: Add `index_post_game_completion` to `DataIndexer`**

In `data_indexer.py`, add after `index_upcoming_games`:

```python
def index_post_game_completion(self, season_id: int) -> int:
    """Poll recently-finished games until all required fields are populated.

    For each post_game game in the season:
    - Fetch events + lineup via existing indexer methods (force=True)
    - Run _is_game_complete; flip to 'complete' or handle deadline
    - On abandon: write/update GameSyncFailure row
    - On manual retry (can_retry=True): reset game to post_game first

    Returns: number of games transitioned (to complete or abandoned).

    Note: incomplete_fields and missing_fields columns are JSON type — assign
    Python lists directly; SQLAlchemy handles serialization.
    """
    from datetime import timedelta
    from app.models.db_models import Game, GameSyncFailure
    from app.services.game_completeness import _is_game_complete, _resolve_game_tier

    now = _utcnow()

    # --- Step 0: Process manual retries (can_retry=True) ---
    try:
        with self.db_service.session_scope() as session:
            retries = (
                session.query(GameSyncFailure)
                .filter_by(can_retry=True)
                .join(Game, GameSyncFailure.game_id == Game.id)
                .filter(Game.season_id == season_id)
                .all()
            )
            for failure in retries:
                game = session.get(Game, failure.game_id)
                if game:
                    game.completeness_status = "post_game"
                    game.give_up_at = now + timedelta(days=3)
                    game.incomplete_fields = None
                    failure.can_retry = False
                    failure.retried_at = now
    except Exception as exc:
        self._logger.warning("index_post_game_completion: retry processing failed: %s", exc)

    # --- Step 1: Load post_game games for this season ---
    try:
        with self.db_service.session_scope() as session:
            games_data = [
                {"id": g.id, "group_id": g.group_id, "game_date": g.game_date,
                 "give_up_at": g.give_up_at}
                for g in session.query(Game).filter(
                    Game.season_id == season_id,
                    Game.completeness_status == "post_game",
                ).all()
            ]
    except Exception as exc:
        self._logger.error("index_post_game_completion: failed to load games: %s", exc)
        return 0

    transitioned = 0

    for gdata in games_data:
        game_id = gdata["id"]
        give_up_at = gdata["give_up_at"]

        # --- Step 2: Fetch data ---
        try:
            self.index_game_events(game_id, season_id, force=True,
                                   game_date=gdata["game_date"])
        except Exception as exc:
            self._logger.warning("post_game_completion: events failed game %d: %s",
                                 game_id, exc)
        try:
            self.index_game_lineup(game_id, season_id, force=True,
                                   game_date=gdata["game_date"])
        except Exception as exc:
            self._logger.warning("post_game_completion: lineup failed game %d: %s",
                                 game_id, exc)

        # --- Step 3: Check completeness and transition ---
        try:
            with self.db_service.session_scope() as session:
                game = session.get(Game, game_id)
                if game is None:
                    continue
                tier = _resolve_game_tier(game, session)
                is_complete, missing = _is_game_complete(game, tier, session)

                game.completeness_checked_at = _utcnow()

                if is_complete:
                    game.completeness_status = "complete"
                    game.incomplete_fields = None
                    transitioned += 1
                elif give_up_at and _utcnow() >= give_up_at:
                    # Past deadline → abandon
                    game.completeness_status = "abandoned"
                    game.incomplete_fields = missing  # JSON column: assign list directly

                    # Upsert GameSyncFailure (update existing if present)
                    failure = (
                        session.query(GameSyncFailure)
                        .filter_by(game_id=game_id)
                        .first()
                    )
                    if failure is None:
                        failure = GameSyncFailure(
                            game_id=game_id,
                            season_id=game.season_id,
                        )
                        session.add(failure)
                    failure.abandoned_at = _utcnow()
                    failure.missing_fields = missing  # JSON column: assign list directly
                    failure.can_retry = False
                    transitioned += 1
                else:
                    # Still within deadline — update missing fields only
                    game.incomplete_fields = missing  # JSON column: assign list directly

        except Exception as exc:
            self._logger.error(
                "post_game_completion: transition failed game %d: %s", game_id, exc
            )

    return transitioned
```

- [ ] **Step 4: Run indexer tests**

```bash
cd backend && .venv/bin/pytest tests/test_game_lifecycle_indexer.py -v
```
Expected: all `PASSED`.

- [ ] **Step 5: Run full test suite**

```bash
cd backend && .venv/bin/pytest tests/ --tb=short 2>&1 | tail -20
```
Expected: no regressions.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/data_indexer.py backend/tests/test_game_lifecycle_indexer.py
git commit -m "feat(indexer): add index_post_game_completion with abandon + manual retry"
```

---

## Chunk 4: Scheduler + Wiring

### Task 6: Add new scheduler policies and remove old ones

**Files:**
- Modify: `backend/app/services/scheduler.py`
- Test: `backend/tests/test_scheduler.py` (extend) or new `backend/tests/test_game_lifecycle_scheduler.py`

Replace the `games`, `game_lineups`, and `game_events` policies with three `upcoming_games_*` policies and one `post_game_completion` policy.

- [ ] **Step 1: Write failing tests for new policies**

```python
# backend/tests/test_game_lifecycle_scheduler.py
import pytest
from app.services.scheduler import POLICIES


def test_old_game_policies_removed():
    """Legacy game/game_lineups/game_events policies must be gone."""
    names = {p["name"] for p in POLICIES}
    assert "games" not in names
    assert "game_lineups" not in names
    assert "game_events" not in names


def test_upcoming_games_policies_exist():
    names = {p["name"] for p in POLICIES}
    assert "upcoming_games_midday" in names
    assert "upcoming_games_evening" in names
    assert "upcoming_games_night" in names


def test_post_game_completion_policy_exists():
    names = {p["name"] for p in POLICIES}
    assert "post_game_completion" in names


def test_upcoming_games_fire_at_correct_hours():
    by_name = {p["name"]: p for p in POLICIES}
    assert by_name["upcoming_games_midday"]["run_at_hour"] == 12
    assert by_name["upcoming_games_evening"]["run_at_hour"] == 18
    assert by_name["upcoming_games_night"]["run_at_hour"] == 23


def test_post_game_completion_has_no_run_at_hour():
    """post_game_completion runs every 2 hours, not at a fixed nightly time."""
    from datetime import timedelta
    by_name = {p["name"]: p for p in POLICIES}
    p = by_name["post_game_completion"]
    assert "run_at_hour" not in p
    assert p["max_age"] == timedelta(hours=2)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && .venv/bin/pytest tests/test_game_lifecycle_scheduler.py -v
```
Expected: `FAILED` — old policies still exist, new ones absent.

- [ ] **Step 3: Edit `POLICIES` in `scheduler.py`**

Find and **remove** the policy dicts with `"name": "games"`, `"name": "game_lineups"`, and `"name": "game_events"` from the `POLICIES` list.

**Add** in their place (keep similar priority ordering — insert around priority 70–82):

```python
# Three daily windows: midday, evening, night. max_age=23h prevents double-firing
# within the same day. On cold-start after all three windows have passed for the
# day, all three will be scheduled for the following day — this is acceptable.
{
    "name":        "upcoming_games_midday",
    "entity_type": "upcoming_games_midday",
    "max_age":     timedelta(hours=23),  # once per day per slot
    "task":        "upcoming_games",
    "scope":       "season",
    "label":       "Upcoming games midday refresh",
    "priority":    70,
    "run_at_hour": 12,
},
{
    "name":        "upcoming_games_evening",
    "entity_type": "upcoming_games_evening",
    "max_age":     timedelta(hours=23),
    "task":        "upcoming_games",
    "scope":       "season",
    "label":       "Upcoming games evening refresh",
    "priority":    71,
    "run_at_hour": 18,
},
{
    "name":        "upcoming_games_night",
    "entity_type": "upcoming_games_night",
    "max_age":     timedelta(hours=23),
    "task":        "upcoming_games",
    "scope":       "season",
    "label":       "Upcoming games night refresh",
    "priority":    72,
    "run_at_hour": 23,
},
{
    "name":        "post_game_completion",
    "entity_type": "post_game_completion",
    "max_age":     timedelta(hours=2),
    "task":        "post_game_completion",
    "scope":       "season",
    "label":       "Post-game completion check",
    "priority":    80,
    # no run_at_hour — runs every 2 hours around the clock
},
```

- [ ] **Step 4: Run scheduler policy tests**

```bash
cd backend && .venv/bin/pytest tests/test_game_lifecycle_scheduler.py -v
```
Expected: all `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/scheduler.py backend/tests/test_game_lifecycle_scheduler.py
git commit -m "feat(scheduler): replace game/game_lineups/game_events with lifecycle-aware jobs"
```

---

### Task 7: Wire new job tasks to admin job handlers

**Files:**
- Modify: `backend/app/main.py` (or wherever admin job tasks are registered — search for `"events"` or `"games"` task string to find the dispatch table)
- Test: `backend/tests/test_admin_indexing.py` (extend)

The scheduler calls `_submit(job_id, season_id, task_name, force, max_tier)` which routes `task_name` to a handler. Find where `"events"`, `"games"`, and `"game_lineups"` are handled and add `"upcoming_games"` and `"post_game_completion"`.

- [ ] **Step 1: Find the dispatch table**

```bash
cd backend && grep -n '"events"\|"games"\|"game_lineups"\|task.*index' app/main.py | head -30
```

Identify the dict/if-elif that maps task names to indexer calls.

- [ ] **Step 2: Write a failing test**

```python
# In backend/tests/test_admin_indexing.py (or new file)
def test_upcoming_games_task_is_registered(admin_client):
    """The admin job dispatch must recognise 'upcoming_games' task."""
    # Trigger via admin API — check that posting an index job with
    # task=upcoming_games returns 200 (not 400 unknown task)
    resp = admin_client.post("/admin/index", data={
        "task": "upcoming_games", "season": "2025"
    })
    assert resp.status_code in (200, 202, 303)  # accepted or redirect


def test_post_game_completion_task_is_registered(admin_client):
    resp = admin_client.post("/admin/index", data={
        "task": "post_game_completion", "season": "2025"
    })
    assert resp.status_code in (200, 202, 303)
```

- [ ] **Step 3: Run to confirm failure**

```bash
cd backend && .venv/bin/pytest tests/test_admin_indexing.py -k "upcoming_games or post_game_completion" -v
```
Expected: task not recognised → non-200 response.

- [ ] **Step 4: Register the new task handlers in the dispatch table**

All admin indexer calls use `await asyncio.to_thread(...)` to avoid blocking the event loop (see existing pattern at lines ~1833, ~1970, ~2107). Follow the same pattern and call `record_season_sync` at the end (matching adjacent handlers):

```python
# ── UPCOMING GAMES ─────────────────────────────────────────────────
if task == "upcoming_games":
    push("info", f"Polling upcoming games for season {season}...")
    n = await asyncio.to_thread(indexer.index_upcoming_games, season, force=force)
    stats["transitioned"] = n
    push("ok", f"Games transitioned to post_game: {n}")
    await asyncio.to_thread(indexer.record_season_sync, "upcoming_games", season, n)
    set_progress(100)

# ── POST-GAME COMPLETION ────────────────────────────────────────────
if task == "post_game_completion":
    push("info", f"Running post-game completion check for season {season}...")
    n = await asyncio.to_thread(indexer.index_post_game_completion, season)
    stats["transitioned"] = n
    push("ok", f"Games transitioned (complete/abandoned): {n}")
    await asyncio.to_thread(indexer.record_season_sync, "post_game_completion", season, n)
    set_progress(100)
```

Also **remove** (or comment out) the handlers for `"games"`, `"game_lineups"`, and `"events"` if they are no longer reachable from the scheduler. Keep them if any admin UI buttons still reference them directly.

- [ ] **Step 5: Run wiring tests**

```bash
cd backend && .venv/bin/pytest tests/test_admin_indexing.py -v
```
Expected: all `PASSED`.

- [ ] **Step 6: Run full test suite**

```bash
cd backend && .venv/bin/pytest tests/ --tb=short 2>&1 | tail -30
```
Expected: all passing.

- [ ] **Step 7: Commit**

```bash
git add backend/app/main.py backend/tests/test_admin_indexing.py
git commit -m "feat(admin): wire upcoming_games and post_game_completion job tasks"
```

---

### Task 8: Admin UI for `GameSyncFailure` (manual retry)

**Files:**
- Modify: `backend/app/main.py` (add route)
- Modify: `backend/templates/admin.html` (or create partial) — add failures section
- Modify: `backend/locales/*/messages.json` (add i18n keys)

- [ ] **Step 1: Add a route to list and retry GameSyncFailure rows**

Find an existing admin-only route in `main.py` (e.g. the admin dashboard route) and copy its `Depends(...)` auth guard exactly — do not invent a new auth pattern. The route must be behind the same session-based PIN auth as all other `/{locale}/admin/` routes.

In `main.py`, add (replacing `...` with the auth dependency copied from adjacent admin routes):

```python
@app.get("/{locale}/admin/game-failures")
async def admin_game_failures(locale: str, request: Request, _=Depends(require_admin)):
    """List abandoned games with missing fields. Admins can trigger retry."""
    failures = []
    with db.session_scope() as session:
        rows = (
            session.query(GameSyncFailure)
            .order_by(GameSyncFailure.abandoned_at.desc())
            .limit(200)
            .all()
        )
        failures = [
            {
                "id": f.id,
                "game_id": f.game_id,
                "season_id": f.season_id,
                "abandoned_at": f.abandoned_at,
                "missing_fields": f.missing_fields or [],  # JSON column, already a list
                "can_retry": bool(f.can_retry),
                "retried_at": f.retried_at,
            }
            for f in rows
        ]
    return templates.TemplateResponse("admin_game_failures.html", {
        "request": request, "locale": locale, "t": get_translations(locale),
        "failures": failures,
    })


@app.post("/{locale}/admin/game-failures/{failure_id}/retry")
async def admin_retry_game_failure(
    locale: str, failure_id: int, request: Request, _=Depends(require_admin)
):
    """Set can_retry=True on a GameSyncFailure row."""
    with db.session_scope() as session:
        failure = session.get(GameSyncFailure, failure_id)
        if failure:
            failure.can_retry = True
    return RedirectResponse(f"/{locale}/admin/game-failures", status_code=303)
```

(`require_admin` is a placeholder name — use whatever dependency the existing admin routes use.)
```

- [ ] **Step 2: Create `backend/templates/admin_game_failures.html`**

Extend `base.html`. Show a table: game_id, season, abandoned_at, missing_fields (formatted as comma-separated), can_retry status, "Retry" button (POST form).

- [ ] **Step 3: Add i18n keys**

In each of `backend/locales/{de,en,fr,it}/messages.json`, add under an `"admin"` section. Use English as placeholder for non-English locales (to be translated later):

```json
"game_failures": "Game Sync Failures",
"retry": "Retry",
"missing_fields": "Missing Fields",
"abandoned_at": "Abandoned At"
```

- [ ] **Step 4: Add a link to the new page from the admin nav**

In `backend/templates/admin.html` (or `base.html` admin section), add a link to `/{locale}/admin/game-failures`.

- [ ] **Step 5: Run smoke test**

```bash
cd backend && .venv/bin/pytest tests/test_routes.py -v -k "admin" --tb=short
```
Expected: existing admin tests still pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py backend/templates/admin_game_failures.html \
        backend/locales/de/messages.json backend/locales/en/messages.json \
        backend/locales/fr/messages.json backend/locales/it/messages.json
git commit -m "feat(admin): add game sync failures page with manual retry"
```

---

## Final Verification

- [ ] **Run full test suite**

```bash
cd backend && .venv/bin/pytest tests/ -v --tb=short 2>&1 | tail -40
```
Expected: all passing, no regressions.

- [ ] **Smoke test the lifecycle end-to-end**

Start dev server, navigate to `/admin`, trigger `upcoming_games` for a recent season, verify:
1. Games with `status=scheduled` stay `upcoming`
2. Any game the API now returns as `finished` flips to `post_game`
3. Trigger `post_game_completion` — games with full data flip to `complete`
4. Check `/admin/game-failures` page loads

- [ ] **Verify old jobs are gone from scheduler queue**

In the admin scheduler panel, confirm `game_events`, `games`, `game_lineups` no longer appear. Confirm `upcoming_games_midday`, `upcoming_games_evening`, `upcoming_games_night`, and `post_game_completion` appear.

- [ ] **Final commit tag**

```bash
git tag game-lifecycle-jobs-complete
```
