# Past Season Games Indexing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add scheduler policies so that games, game events, and game lineups are automatically indexed for past seasons that don't have them yet.

**Architecture:** Add a `past_only` flag (inverse of the existing `current_only`) to two new scheduler policies — `games` and `game_events` — that use already-existing task dispatch paths. The `requires` chain (leagues→games→game_events) ensures correct ordering. The existing "frozen once indexed" and auto-freeze logic handle cleanup automatically.

**Tech Stack:** Python, SQLAlchemy, pytest. All changes in `backend/`. Run commands from `backend/` with `.venv/bin/` binaries.

---

### Task 1: Add `past_only` guard to `_maybe_schedule`

**Files:**
- Modify: `backend/app/services/scheduler.py` (around line 994)
- Test: `backend/tests/test_scheduler.py`

- [ ] **Step 1: Write the failing test**

Add a new test class at the end of `backend/tests/test_scheduler.py` (before the final standalone functions):

```python
class TestPastOnlyFlag:
    """past_only policies must not run for the current season."""

    def test_past_only_policy_skipped_for_current_season(self):
        """A past_only policy must return early when is_current_season=True."""
        from unittest.mock import MagicMock, patch
        from app.services.scheduler import Scheduler

        sched = Scheduler.__new__(Scheduler)
        sched._min_season = None
        sched._excluded_seasons = []
        sched._max_concurrent = 2
        sched._policy_tiers = {}
        sched._enabled = True
        sched._queue = []
        sched._history = []
        sched._running = False

        past_only_policy = {
            "name": "games",
            "entity_type": "games",
            "task": "games",
            "scope": "season",
            "past_only": True,
            "label": "Games (past seasons)",
            "max_age": __import__("datetime").timedelta(days=7),
            "priority": 55,
            "run_at_hour": 3,
        }

        mock_session = MagicMock()
        # _maybe_schedule should return early before any DB query for is_frozen
        # We verify by asserting nothing was enqueued
        sched._maybe_schedule(mock_session, past_only_policy, season=2025, is_current_season=True)

        assert sched._queue == [], "past_only policy must not be queued for current season"

    def test_past_only_policy_runs_for_past_season(self):
        """A past_only policy must NOT be skipped when is_current_season=False."""
        from unittest.mock import MagicMock, patch
        from datetime import timedelta
        from app.services.scheduler import Scheduler

        sched = Scheduler.__new__(Scheduler)
        sched._min_season = None
        sched._excluded_seasons = []
        sched._max_concurrent = 2
        sched._policy_tiers = {}
        sched._enabled = True
        sched._queue = []
        sched._history = []
        sched._running = False

        past_only_policy = {
            "name": "games",
            "entity_type": "games",
            "task": "games",
            "scope": "season",
            "past_only": True,
            "requires": "leagues",
            "label": "Games (past seasons)",
            "max_age": timedelta(days=7),
            "priority": 55,
            "run_at_hour": 3,
        }

        mock_session = MagicMock()
        # is_frozen → False
        mock_session.query.return_value.filter.return_value.scalar.return_value = False
        # _last_sync_for (leagues prerequisite) → a datetime (leagues done)
        # _last_sync_for (games entity_type) → None (not yet indexed)
        from datetime import datetime, timezone
        leagues_done = datetime(2026, 3, 30, 3, 0, 0)

        call_count = [0]
        def fake_first():
            call_count[0] += 1
            # First call: is_frozen scalar (handled above by mock_session)
            # _last_sync_for calls .first() on the query
            if call_count[0] == 1:
                return (leagues_done,)  # leagues prerequisite completed
            return None  # games not yet synced

        mock_session.query.return_value.filter.return_value.order_by.return_value.first = fake_first
        mock_session.query.return_value.filter.return_value.scalar.return_value = False

        with patch("app.services.scheduler._last_sync_for") as mock_lsf, \
             patch("app.services.scheduler._last_attempt_for", return_value=None):
            mock_lsf.side_effect = lambda s, entity_type, season: (
                leagues_done if entity_type == "leagues" else None
            )
            sched._maybe_schedule(mock_session, past_only_policy, season=2019, is_current_season=False)

        assert len(sched._queue) == 1, "past_only policy should be queued for past season"
        assert sched._queue[0].policy_name == "games"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && .venv/bin/pytest tests/test_scheduler.py::TestPastOnlyFlag -v
```

Expected: both tests FAIL — `test_past_only_policy_skipped_for_current_season` fails because the current code has no `past_only` guard (the policy would run through to the `current_only` check and possibly enqueue), and `test_past_only_policy_runs_for_past_season` may also fail.

- [ ] **Step 3: Add the `past_only` guard in `_maybe_schedule`**

In `backend/app/services/scheduler.py`, find the block around line 992–995:

```python
        # current_only policies are live data that changes every match — they must
        # never run on past seasons, even for an initial sync.
        if policy.get("current_only") and not is_current_season:
            return
```

Add the `past_only` guard immediately after it:

```python
        # current_only policies are live data that changes every match — they must
        # never run on past seasons, even for an initial sync.
        if policy.get("current_only") and not is_current_season:
            return

        # past_only policies exist specifically for past seasons (e.g. games, game_events)
        # — the current season's game indexing is owned by upcoming_games/post_game_completion.
        if policy.get("past_only") and is_current_season:
            return
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && .venv/bin/pytest tests/test_scheduler.py::TestPastOnlyFlag -v
```

Expected: both PASS.

- [ ] **Step 5: Run full scheduler test suite to verify no regressions**

```bash
cd backend && .venv/bin/pytest tests/test_scheduler.py -v
```

Expected: all existing tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/scheduler.py backend/tests/test_scheduler.py
git commit -m "feat: add past_only guard to scheduler _maybe_schedule"
```

---

### Task 2: Add `games` and `game_events` policies to POLICIES

**Files:**
- Modify: `backend/app/services/scheduler.py` (around line 122)
- Test: `backend/tests/test_scheduler.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_scheduler.py`, inside the existing `class TestPoliciesDefinition:` (which starts around line 322):

```python
    def test_games_policy_exists_and_is_past_only(self):
        """games policy must exist, be past_only, and require leagues."""
        from app.services.scheduler import POLICIES

        p = next((p for p in POLICIES if p["name"] == "games"), None)
        assert p is not None, "games policy not found in POLICIES"
        assert p["past_only"] is True
        assert p["requires"] == "leagues"
        assert p["task"] == "games"
        assert p["scope"] == "season"
        assert p["run_at_hour"] == 3

    def test_game_events_policy_exists_and_is_past_only(self):
        """game_events policy must exist, be past_only, and require games."""
        from app.services.scheduler import POLICIES

        p = next((p for p in POLICIES if p["name"] == "game_events"), None)
        assert p is not None, "game_events policy not found in POLICIES"
        assert p["past_only"] is True
        assert p["requires"] == "games"
        assert p["task"] == "events"
        assert p["scope"] == "season"
        assert p["run_at_hour"] == 3

    def test_games_policy_priority_between_leagues_and_upcoming(self):
        """games must have priority between leagues(50) and upcoming_games_noon(70)."""
        from app.services.scheduler import POLICIES

        leagues_p = next(p["priority"] for p in POLICIES if p["name"] == "leagues")
        games_p = next(p["priority"] for p in POLICIES if p["name"] == "games")
        game_events_p = next(p["priority"] for p in POLICIES if p["name"] == "game_events")
        upcoming_p = next(p["priority"] for p in POLICIES if p["name"] == "upcoming_games_noon")

        assert leagues_p < games_p < game_events_p < upcoming_p
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && .venv/bin/pytest tests/test_scheduler.py::TestPoliciesDefinition::test_games_policy_exists_and_is_past_only tests/test_scheduler.py::TestPoliciesDefinition::test_game_events_policy_exists_and_is_past_only tests/test_scheduler.py::TestPoliciesDefinition::test_games_policy_priority_between_leagues_and_upcoming -v
```

Expected: all three FAIL with "games policy not found in POLICIES".

- [ ] **Step 3: Add the two new policies to POLICIES**

In `backend/app/services/scheduler.py`, find the block ending at line 122:

```python
    {
        "name": "leagues",
        "entity_type": "leagues",
        "max_age": timedelta(days=7),
        "task": "leagues",
        "scope": "season",
        "label": "Leagues refresh",
        "priority": 50,
        "run_at_hour": 3,
    },
    # ── Upcoming games polling — schedule changes (noon / evening / night) ───
```

Replace with:

```python
    {
        "name": "leagues",
        "entity_type": "leagues",
        "max_age": timedelta(days=7),
        "task": "leagues",
        "scope": "season",
        "label": "Leagues refresh",
        "priority": 50,
        "run_at_hour": 3,
    },
    # ── Past-season game indexing — run once, then frozen ────────────────────
    # These policies fill in games/events/lineups for seasons that were added
    # to the DB after the season ended (e.g. via gap detection).  current_only
    # upcoming_games already owns this data for the active season.
    {
        "name": "games",
        "entity_type": "games",
        "task": "games",          # runs leagues → league_groups → games → team_names
        "scope": "season",
        "past_only": True,        # never runs for the current season
        "requires": "leagues",    # wait until leagues are indexed for this season
        "label": "Games (past seasons)",
        "max_age": timedelta(days=7),
        "priority": 55,
        "run_at_hour": 3,
    },
    {
        "name": "game_events",
        "entity_type": "game_events",
        "task": "events",         # runs game_events + game_lineups together in one pass
        "scope": "season",
        "past_only": True,        # never runs for the current season
        "requires": "games",      # wait until games are indexed for this season
        "label": "Game events + lineups (past seasons)",
        "max_age": timedelta(days=7),
        "priority": 60,
        "run_at_hour": 3,
    },
    # ── Upcoming games polling — schedule changes (noon / evening / night) ───
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && .venv/bin/pytest tests/test_scheduler.py::TestPoliciesDefinition -v
```

Expected: all tests in `TestPoliciesDefinition` PASS, including the three new ones.

- [ ] **Step 5: Run full test suite**

```bash
cd backend && .venv/bin/pytest tests/test_scheduler.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/scheduler.py backend/tests/test_scheduler.py
git commit -m "feat: add games and game_events policies for past season indexing"
```

---

### Task 3: Verify end-to-end with the running app

**Files:** none modified — this is a verification step only.

- [ ] **Step 1: Check current scheduler diagnostic in the admin**

Hit the admin API to see the current scheduler state:

```bash
curl -s http://localhost:8000/admin/api/scheduler-diag | python3 -m json.tool | head -60
```

Or open `https://swissunihockeystats.mennylenderr.ch/admin` → Scheduler tab → check that `games` and `game_events` policies appear in the policy list.

- [ ] **Step 2: Confirm past seasons are queued for games**

Check the scheduler queue in the admin jobs list. Seasons 2018/2019/2020 should have `games` jobs queued for the next 03:00 UTC window (since `leagues` was already indexed for them at the last nightly run).

In the admin jobs panel, look for entries with `task=games, season=2018/2019/2020, run_at≈next 03:00 UTC`.

- [ ] **Step 3: Verify `game_events` is NOT queued for current season (2025)**

In the admin jobs list, confirm there is no `games` or `game_events` job for `season=2025`. The `past_only` guard must exclude the current season.

- [ ] **Step 4: Deploy to production and monitor**

```bash
cd ~/dockerimages/SwissUnihockeyStats
docker compose build --no-cache && docker compose up -d --force-recreate
```

After restart, watch logs for the 03:00 UTC window:

```bash
docker logs -f $(docker ps -q --filter "name=swiss") 2>&1 | grep -E "(games|game_events|season=201[89]|season=2020)"
```

Expected: `launching job ... task=games season=2018/2019/2020` at 03:00 UTC, followed later by `launching job ... task=events season=2018/2019/2020`.

- [ ] **Step 5: Verify games appear in DB after run**

```bash
docker exec $(docker ps -q --filter "name=swiss") python3 -c "
import sqlite3
conn = sqlite3.connect('/app/data/swissunihockey.db')
c = conn.cursor()
c.execute('SELECT season_id, COUNT(*) FROM games GROUP BY season_id ORDER BY season_id')
for row in c.fetchall(): print(row)
"
```

Expected: seasons 2018, 2019, 2020 now show non-zero game counts (similar to 2021–2024 which have 18k–21k games each).

---

## Self-Review

**Spec coverage:**
- ✓ `past_only` flag added to `_maybe_schedule` (Task 1)
- ✓ Two new policies `games` and `game_events` added to POLICIES (Task 2)
- ✓ `requires` chain: leagues→games→game_events (Task 2 policy dicts)
- ✓ Current season excluded via `past_only` guard (Task 1 guard + Task 1 test)
- ✓ Interaction with freeze logic: not changed, verified correct in tests (existing tests pass)
- ✓ Sentinels already in place in main.py — no main.py changes needed (spec Part 2)

**Placeholder scan:** No TBDs. All code blocks are complete. Commands have expected output.

**Type consistency:** `past_only` used consistently in guard and policy dicts. `requires` values match `entity_type` values of prerequisite policies (`"leagues"` and `"games"`).
