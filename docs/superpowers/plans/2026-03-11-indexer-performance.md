# Indexer Performance Improvements Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce indexing job runtimes by fixing two structural bottlenecks and exposing a tunable concurrency setting in the admin panel.

**Architecture:** Three independent changes: (1) expose `player_game_stats` thread-pool size in `scheduler_config.json` and admin UI; (2) raise hardcoded batch constants for games and lineup jobs; (3) refactor `index_player_stats_for_season` from a serial loop inside a single session to the same Phase 1 (parallel API fetches) + Phase 2 (batched DB writes) pattern already used by `index_player_game_stats_for_season`.

**Tech Stack:** Python 3.9+, FastAPI, SQLAlchemy, ThreadPoolExecutor, Jinja2 admin templates

**Spec:** `docs/superpowers/specs/2026-03-11-indexer-performance-design.md`

---

## Chunk 1: Configurable `max_workers` for player_game_stats

### Task 1: Add `player_game_stats_workers` to scheduler config

**Files:**
- Modify: `backend/app/services/scheduler.py:424-458` (`_load_state`, `_save_state`, `_reload_config`, `__init__`)

---

- [ ] **Step 1: Write failing test**

```python
# tests/test_scheduler.py  — add these tests
def test_player_game_stats_workers_persists(tmp_path, monkeypatch):
    """player_game_stats_workers is saved to and loaded from config."""
    import json
    from app.services.scheduler import Scheduler

    cfg = tmp_path / "scheduler_config.json"
    monkeypatch.setattr("app.services.scheduler._CONFIG_PATH", str(cfg))
    sched = Scheduler(submit_job=None)

    sched.set_player_game_stats_workers(12)

    data = json.loads(cfg.read_text())
    assert data["player_game_stats_workers"] == 12
    assert sched._player_game_stats_workers == 12

    # Reload from file via a fresh Scheduler (tests _load_state)
    sched2 = Scheduler(submit_job=None)
    assert sched2._player_game_stats_workers == 12


def test_player_game_stats_workers_reload_config(tmp_path, monkeypatch):
    """_reload_config picks up player_game_stats_workers written externally."""
    import json
    from app.services.scheduler import Scheduler

    cfg = tmp_path / "scheduler_config.json"
    monkeypatch.setattr("app.services.scheduler._CONFIG_PATH", str(cfg))
    sched = Scheduler(submit_job=None)

    # Simulate another process writing the config file directly
    cfg.write_text(json.dumps({"player_game_stats_workers": 15}))
    sched._reload_config()

    assert sched._player_game_stats_workers == 15
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd backend && .venv/bin/pytest tests/test_scheduler.py::test_player_game_stats_workers_persists -v
```

Expected: `AttributeError: 'Scheduler' object has no attribute 'set_player_game_stats_workers'`

- [ ] **Step 3: Implement in `scheduler.py`**

All config attributes are initialised inside `_load_state()` / its `except` branch, not in `__init__`. Follow the same pattern — do NOT add a separate init in `__init__`.

In `_load_state` success path (line 431, after the `_max_concurrent` line):
```python
self._player_game_stats_workers: int = max(1, int(data.get("player_game_stats_workers", 10)))
```

In the `except` block of `_load_state` (line 437, after `self._max_concurrent = 2`):
```python
self._player_game_stats_workers = 10
```

In `_save_state` JSON dict (line 451, after `"max_concurrent"`):
```python
"player_game_stats_workers": self._player_game_stats_workers,
```

In `_reload_config` (line 473, after the `_max_concurrent` line):
```python
self._player_game_stats_workers = max(1, int(data.get("player_game_stats_workers", 10)))
```

After `set_max_concurrent` (line 531), add new method:
```python
def set_player_game_stats_workers(self, n: int):
    """Set the thread-pool size for player_game_stats Phase 1 API fetches."""
    self._player_game_stats_workers = max(1, n)
    self._save_state()
    logger.info("[scheduler] player_game_stats_workers set to %d", self._player_game_stats_workers)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_scheduler.py::test_player_game_stats_workers_persists -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/scheduler.py backend/tests/test_scheduler.py
git commit -m "feat(scheduler): add player_game_stats_workers config field"
```

---

### Task 2: Wire `max_workers` through `_run()` and expose admin endpoint

**Files:**
- Modify: `backend/app/main.py:1480-1485` (admin endpoint), `backend/app/main.py:1924-1928` (`_run`)

---

- [ ] **Step 1: Write failing test**

```python
# tests/test_admin_indexing.py — add this test
def test_player_game_stats_workers_endpoint(admin_client):
    """POST /admin/api/scheduler with action=player_game_stats_workers updates the setting."""
    r = admin_client.post(
        "/admin/api/scheduler",
        json={"action": "player_game_stats_workers", "value": 8},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["player_game_stats_workers"] == 8
```

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/bin/pytest tests/test_admin_indexing.py::test_player_game_stats_workers_endpoint -v
```

Expected: FAIL (404 or 400 — action not recognised)

- [ ] **Step 3: Add endpoint branch and wire `_run()`**

In `main.py` after the `max_concurrent` block (line 1485), add:
```python
if action == "player_game_stats_workers":
    n = payload.get("value", 10)
    if not isinstance(n, int) or n < 1:
        raise HTTPException(status_code=400, detail="value must be a positive integer")
    sched.set_player_game_stats_workers(n)
    return {"ok": True, "player_game_stats_workers": sched._player_game_stats_workers}
```

In `_run()` at the `player_game_stats` dispatch (line 1924), add the `max_workers` kwarg:
```python
pgstats_n = await asyncio.to_thread(
    indexer.index_player_game_stats_for_season,
    season_id=season, force=force, exact_tier=_exact_tier,
    on_progress=set_progress,
    max_workers=sched._player_game_stats_workers,
)
```

- [ ] **Step 4: Run test**

```bash
.venv/bin/pytest tests/test_admin_indexing.py::test_player_game_stats_workers_endpoint -v
```

Expected: PASS

- [ ] **Step 5: Run full test suite**

```bash
.venv/bin/pytest -q --ignore=tests/test_api_endpoints.py
```

Expected: same pass/fail count as before (12 pre-existing failures, all others pass)

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py
git commit -m "feat: wire player_game_stats_workers through _run() and admin endpoint"
```

---

### Task 3: Admin UI — add `max_workers` input to scheduler settings

**Files:**
- Modify: admin HTML template that renders the scheduler settings panel (find with `grep -r "max_concurrent" backend/templates/`)

---

- [ ] **Step 1: Find the template**

```bash
grep -r "max_concurrent" backend/templates/ -l
```

- [ ] **Step 2: Add the input**

Locate the `max_concurrent` input element. Directly below it, add an analogous input for `player_game_stats_workers`. Follow the exact same HTML pattern and JavaScript wiring used for `max_concurrent`. The endpoint call should POST `{"action": "player_game_stats_workers", "value": <int>}` to `/admin/api/scheduler`.

Label: `"API workers (player stats)"`. Add a short help text: `"Thread pool size for player_game_stats Phase 1 API fetches (default 10, max ≈ 20)"`.

- [ ] **Step 3: Verify visually**

Start the dev server and open the admin scheduler settings. Confirm the new input appears, can be edited, and the value persists after page reload.

```bash
cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000
```

- [ ] **Step 4: Commit**

```bash
git add backend/templates/
git commit -m "feat(admin): add player_game_stats workers input to scheduler settings"
```

---

## Chunk 2: Increase batch constants

### Task 4: Raise `_GAMES_BATCH` and `_EV_BATCH`

**Files:**
- Modify: `backend/app/main.py:1984` (`_GAMES_BATCH`), `backend/app/main.py:2084` (`_EV_BATCH`)

---

- [ ] **Step 1: Change constants**

In `main.py` line 1984:
```python
_GAMES_BATCH = 4   # was 2
```

In `main.py` line 2084:
```python
_EV_BATCH = 6   # was 2
```

- [ ] **Step 2: Run tests**

```bash
.venv/bin/pytest -q --ignore=tests/test_api_endpoints.py
```

Expected: same pass/fail as baseline

- [ ] **Step 3: Commit**

```bash
git add backend/app/main.py
git commit -m "perf: raise _GAMES_BATCH 2→4 and _EV_BATCH 2→6"
```

---

## Chunk 3: `player_stats` Phase 1/2 refactor

### Task 5: Extract write logic from `_upsert_player_stats_from_api`

The goal is to separate the API call from the DB write so Phase 1 can run the API call in parallel without holding any session.

**Files:**
- Modify: `backend/app/services/data_indexer.py:764-921`

---

- [ ] **Step 1: Write test for the new helper**

```python
# tests/test_player_stats_phase2.py (new file)
from unittest.mock import MagicMock, patch
from contextlib import contextmanager
from app.services.data_indexer import DataIndexer, _PlayerStatsFetchResult

def _make_indexer():
    db = MagicMock()
    db.session_scope = MagicMock()
    return DataIndexer.__new__(DataIndexer)

def test_apply_player_stats_result_upserts_rows():
    """_apply_player_stats_result writes PlayerStatistics rows from raw API data."""
    from app.services.data_indexer import DataIndexer

    raw = {
        "data": {
            "regions": [{
                "rows": [{
                    "cells": [
                        {"text": "2025/26"},   # season
                        {"text": "NLA"},        # league
                        {"text": "Team A"},     # team
                        {"text": "30"},         # games
                        {"text": "10"},         # goals
                        {"text": "5"},          # assists
                        {"text": "15"},         # points
                        {"text": "2"},          # pen_2min
                        {"text": "0"},          # pen_5min
                        {"text": "0"},          # pen_10min
                        {"text": "0"},          # pen_match
                    ]
                }]
            }]
        }
    }

    session = MagicMock()
    session.query.return_value.join.return_value.filter.return_value.all.return_value = []
    session.query.return_value.filter.return_value.first.return_value = None
    session.no_autoflush = MagicMock(__enter__=lambda s: s, __exit__=lambda s, *a: False)

    indexer = DataIndexer.__new__(DataIndexer)
    staged = {}
    count = indexer._apply_player_stats_result(session, 99, raw, 2025, "2025/26", staged)
    assert count == 1
    session.add.assert_called_once()
```

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/bin/pytest tests/test_player_stats_phase2.py -v
```

Expected: `AttributeError: _apply_player_stats_result`

- [ ] **Step 3: Extract `_apply_player_stats_result`**

Cut lines 802–921 from `_upsert_player_stats_from_api` (everything after the API call, starting from `regions = stats_data.get(...)`) and move them into a new method:

```python
def _apply_player_stats_result(
    self,
    session,
    person_id: int,
    stats_data: dict,
    season_id: int,
    season_label: str,
    staged: dict,
) -> int:
    """Write PlayerStatistics rows from a pre-fetched API response.

    Accepts the raw dict returned by client.get_player_stats() and upserts
    matching PlayerStatistics rows using the supplied session.
    Returns the number of rows upserted.
    """
    # (paste the existing logic: regions loop, gc_map/tid_map lookup, upsert)
    ...
    return count
```

Then slim `_upsert_player_stats_from_api` to:

```python
def _upsert_player_stats_from_api(self, person_id, season_id, season_label, session, staged):
    try:
        stats_data = self.client.get_player_stats(person_id)
    except Exception as exc:
        import requests as _req
        if isinstance(exc, _req.HTTPError) and exc.response is not None and exc.response.status_code >= 500:
            logger.debug("API 5xx for player stats %s: %s", person_id, exc)
            return 0, True
        logger.debug("Could not fetch stats for player %s: %s", person_id, exc)
        return 0, False
    return self._apply_player_stats_result(session, person_id, stats_data, season_id, season_label, staged), False
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_player_stats_phase2.py tests/test_player_stats_skip_logic.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/data_indexer.py backend/tests/test_player_stats_phase2.py
git commit -m "refactor: extract _apply_player_stats_result for Phase 1/2 split"
```

---

### Task 6: Add `_PlayerStatsFetchResult` and `_fetch_player_stats_raw`

**Files:**
- Modify: `backend/app/services/data_indexer.py` (near line 28 for the dataclass, anywhere suitable for the method)

---

- [ ] **Step 1: Write test**

```python
# tests/test_player_stats_phase2.py — add:

def test_fetch_player_stats_raw_returns_result():
    """_fetch_player_stats_raw wraps the API call into a _PlayerStatsFetchResult."""
    from app.services.data_indexer import DataIndexer, _PlayerStatsFetchResult
    import requests

    client = MagicMock()
    client.get_player_stats.return_value = {"data": {}}

    indexer = DataIndexer.__new__(DataIndexer)
    indexer.client = client

    result = indexer._fetch_player_stats_raw(42)
    assert isinstance(result, _PlayerStatsFetchResult)
    assert result.player_id == 42
    assert result.api_error is False


def test_fetch_player_stats_raw_marks_5xx_as_api_error():
    import requests
    from app.services.data_indexer import DataIndexer, _PlayerStatsFetchResult

    client = MagicMock()
    resp = MagicMock()
    resp.status_code = 503
    client.get_player_stats.side_effect = requests.HTTPError(response=resp)

    indexer = DataIndexer.__new__(DataIndexer)
    indexer.client = client

    result = indexer._fetch_player_stats_raw(42)
    assert result.api_error is True
```

- [ ] **Step 2: Run to verify fails**

```bash
.venv/bin/pytest tests/test_player_stats_phase2.py::test_fetch_player_stats_raw_returns_result -v
```

Expected: `AttributeError`

- [ ] **Step 3: Add dataclass and method**

Near line 28 (after `_PlayerGameStatsFetchResult`), add:
```python
@dataclass
class _PlayerStatsFetchResult:
    """Result of a Phase-1 API fetch for one player's seasonal stats."""
    player_id: int
    raw_data: dict = field(default_factory=dict)
    api_error: bool = False  # True only for HTTP 5xx — increments skip counter
```

Add method to `DataIndexer`:
```python
def _fetch_player_stats_raw(self, person_id: int) -> "_PlayerStatsFetchResult":
    """Phase-1 worker: fetch seasonal stats for one player (no DB access)."""
    try:
        raw = self.client.get_player_stats(person_id)
        return _PlayerStatsFetchResult(player_id=person_id, raw_data=raw)
    except Exception as exc:
        import requests as _req
        is_5xx = (
            isinstance(exc, _req.HTTPError)
            and exc.response is not None
            and exc.response.status_code >= 500
        )
        return _PlayerStatsFetchResult(player_id=person_id, api_error=is_5xx)
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_player_stats_phase2.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/data_indexer.py backend/tests/test_player_stats_phase2.py
git commit -m "feat: add _PlayerStatsFetchResult and _fetch_player_stats_raw"
```

---

### Task 7: Refactor `index_player_stats_for_season` to Phase 1/2

**Files:**
- Modify: `backend/app/services/data_indexer.py:943-1081`

---

- [ ] **Step 1: Write integration test**

```python
# tests/test_player_stats_phase2.py — add:
import math
from contextlib import contextmanager

def test_player_stats_phase2_uses_batch_sessions():
    """_run_player_stats_phase2 opens ceil(n/BATCH)+1 sessions."""
    from app.services.data_indexer import DataIndexer, _PlayerStatsFetchResult

    session = MagicMock()
    session.query.return_value.join.return_value.filter.return_value.all.return_value = []
    session.query.return_value.filter.return_value.first.return_value = None
    session.no_autoflush = MagicMock(__enter__=lambda s: s, __exit__=lambda s, *a: False)

    call_count = 0

    @contextmanager
    def counting_scope():
        nonlocal call_count
        call_count += 1
        yield session

    db = MagicMock()
    db.session_scope = counting_scope

    indexer = DataIndexer.__new__(DataIndexer)
    indexer.db_service = db
    indexer._API_FAILURE_THRESHOLD = 3
    indexer._API_SKIP_DAYS = 7
    indexer._PLAYER_STATS_PHASE2_BATCH_SIZE = 300

    n_players = 5
    results = [
        _PlayerStatsFetchResult(player_id=i, raw_data={"data": {"regions": []}})
        for i in range(n_players)
    ]

    with patch.object(indexer, "_mark_sync_complete"), \
         patch.object(indexer, "_apply_player_stats_result", return_value=0):
        indexer._run_player_stats_phase2(
            fetch_results=results,
            season_id=2025,
            season_label="2025/26",
            entity_type="player_stats_t1",
            entity_id="season_player_stats:t1:2025",
            exact_tier=1,
            now=datetime.now(timezone.utc),
        )

    expected = math.ceil(n_players / 300) + 1  # 1 batch + 1 tier mark
    assert call_count == expected
```

- [ ] **Step 2: Run to verify fails**

```bash
.venv/bin/pytest tests/test_player_stats_phase2.py::test_player_stats_phase2_uses_batch_sessions -v
```

Expected: `AttributeError: _run_player_stats_phase2`

- [ ] **Step 3: Add `_run_player_stats_phase2` and `_PLAYER_STATS_PHASE2_BATCH_SIZE`**

Add constant near `_PHASE2_BATCH_SIZE`:
```python
_PLAYER_STATS_PHASE2_BATCH_SIZE = 300
```

Add method after `_run_phase2`:
```python
def _run_player_stats_phase2(
    self,
    fetch_results: list,
    season_id: int,
    season_label: str,
    entity_type: str,
    entity_id: str,
    exact_tier: Optional[int],
    now: datetime,
) -> int:
    """Phase 2: write player seasonal stats in batches to limit SQLite lock time.

    Each batch of _PLAYER_STATS_PHASE2_BATCH_SIZE players gets its own
    session_scope() — the write lock is held for only a few seconds per batch.
    Per-player SyncStatus rows committed per batch enable checkpoint resume.
    """
    total = 0
    for batch_start in range(0, len(fetch_results), self._PLAYER_STATS_PHASE2_BATCH_SIZE):
        batch = fetch_results[batch_start : batch_start + self._PLAYER_STATS_PHASE2_BATCH_SIZE]
        with self.db_service.session_scope() as session:
            staged: dict = {}
            for result in batch:
                pid = result.player_id
                entity_id_p = f"player_stats:{pid}:{season_id}"

                if result.api_error:
                    player = session.query(Player).filter(Player.person_id == pid).first()
                    if player is not None:
                        player.api_failures = (player.api_failures or 0) + 1
                        if player.api_failures >= self._API_FAILURE_THRESHOLD:
                            player.api_skip_until = now + timedelta(days=self._API_SKIP_DAYS)
                            logger.info(
                                "player_stats: player %s hit %d API failures; skipping until %s",
                                pid, player.api_failures, player.api_skip_until,
                            )
                    continue

                n = self._apply_player_stats_result(
                    session, pid, result.raw_data, season_id, season_label, staged
                )
                # Stamp checkpoint even when n == 0 (fetched OK, just no rows this season).
                # Only api_error players are skipped — they should be retried next run.
                self._mark_sync_complete(session, "player_stats", entity_id_p, n)
                if n > 0:
                    player = session.query(Player).filter(Player.person_id == pid).first()
                    if player is not None and (player.api_failures or 0) > 0:
                        player.api_failures = 0
                        player.api_skip_until = None
                    total += n

    with self.db_service.session_scope() as session:
        self._mark_sync_complete(session, entity_type, entity_id, total)
        if exact_tier is None:
            for t in range(1, 7):
                self._mark_sync_complete(
                    session,
                    f"player_stats_t{t}",
                    f"season_player_stats:t{t}:{season_id}",
                    total,
                )
    return total
```

- [ ] **Step 4: Run test**

```bash
.venv/bin/pytest tests/test_player_stats_phase2.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/data_indexer.py backend/tests/test_player_stats_phase2.py
git commit -m "feat: add _run_player_stats_phase2 with batched session writes"
```

---

### Task 8: Replace serial loop in `index_player_stats_for_season` with Phase 1/2

**Files:**
- Modify: `backend/app/services/data_indexer.py:943-1081` (full replacement of the body)

---

- [ ] **Step 1: Write integration test for the full function**

```python
# tests/test_player_stats_phase2.py — add:
from unittest.mock import patch

def test_index_player_stats_for_season_uses_parallel_phase1():
    """index_player_stats_for_season calls _fetch_player_stats_raw per player,
    not _upsert_player_stats_from_api."""
    from app.services.data_indexer import DataIndexer

    session = MagicMock()
    session.query.return_value.filter.return_value.distinct.return_value.all.return_value = [
        (1,), (2,), (3,),
    ]
    session.query.return_value.filter.return_value.all.return_value = []  # skip_ids

    @contextmanager
    def fake_scope():
        yield session

    db = MagicMock()
    db.session_scope = fake_scope

    indexer = DataIndexer.__new__(DataIndexer)
    indexer.db_service = db
    indexer._API_FAILURE_THRESHOLD = 3
    indexer._API_SKIP_DAYS = 7
    indexer._PLAYER_STATS_PHASE2_BATCH_SIZE = 300
    indexer._should_update = MagicMock(return_value=True)
    indexer.bulk_already_indexed = MagicMock(return_value=set())

    fetch_results = [MagicMock(player_id=i, api_error=False, raw_data={}) for i in (1, 2, 3)]

    with patch.object(indexer, "_fetch_player_stats_raw", side_effect=fetch_results) as mock_fetch, \
         patch.object(indexer, "_run_player_stats_phase2", return_value=3) as mock_phase2:
        result = indexer.index_player_stats_for_season(season_id=2025, force=False)

    assert mock_fetch.call_count == 3
    assert mock_phase2.called
    assert result == 3
```

- [ ] **Step 2: Run to verify fails**

```bash
.venv/bin/pytest tests/test_player_stats_phase2.py::test_index_player_stats_for_season_uses_parallel_phase1 -v
```

Expected: FAIL (still uses old serial loop)

- [ ] **Step 3: Replace body of `index_player_stats_for_season`**

Replace lines 975–1081 (the `try/except` block that holds the big session) with:

```python
        # ── Pre-fetch season label (one short read) ──────────────────────────
        from app.models.db_models import Season as SeasonModel
        with self.db_service.session_scope() as session:
            season_row = session.get(SeasonModel, season_id)
            season_label = season_row.text if season_row and season_row.text else str(season_id)

        # ── Collect eligible player IDs ───────────────────────────────────────
        with self.db_service.session_scope() as session:
            from app.models.db_models import GamePlayer as _GamePlayer, Team as _TTeam
            if exact_tier is not None:
                tier_team_ids = {
                    t.id for t in session.query(_TTeam)
                    .filter(_TTeam.season_id == season_id).all()
                    if league_tier(t.league_id or 0) == exact_tier
                }
                tp_ids = {
                    r[0] for r in
                    session.query(TeamPlayer.player_id)
                    .filter(
                        TeamPlayer.season_id == season_id,
                        TeamPlayer.team_id.in_(tier_team_ids),
                    ).distinct().all()
                }
                gp_ids = {
                    r[0] for r in
                    session.query(_GamePlayer.player_id)
                    .filter(
                        _GamePlayer.season_id == season_id,
                        _GamePlayer.team_id.in_(tier_team_ids),
                    ).distinct().all()
                }
            else:
                tp_ids = {
                    r[0] for r in
                    session.query(TeamPlayer.player_id)
                    .filter(TeamPlayer.season_id == season_id)
                    .distinct().all()
                }
                gp_ids = {
                    r[0] for r in
                    session.query(_GamePlayer.player_id)
                    .filter(_GamePlayer.season_id == season_id)
                    .distinct().all()
                }
            player_ids = list(tp_ids | gp_ids)

        if not player_ids:
            logger.info("No players found for season %s%s", season_id, tier_lbl)
            if exact_tier is not None:
                with self.db_service.session_scope() as session:
                    self._mark_sync_complete(session, entity_type, entity_id, 0)
            return 0

        # Exclude players whose API skip window is still active
        now = datetime.now(timezone.utc)
        with self.db_service.session_scope() as session:
            skip_ids = {
                r[0] for r in session.query(Player.person_id)
                .filter(Player.api_skip_until.isnot(None), Player.api_skip_until > now)
                .all()
            }
        if skip_ids:
            logger.info("player_stats: skipping %d player(s) with active API skip window", len(skip_ids))
        player_ids = [pid for pid in player_ids if pid not in skip_ids]

        if not player_ids:
            logger.info("No eligible players to process for season %s%s after skip filter", season_id, tier_lbl)
            with self.db_service.session_scope() as session:
                self._mark_sync_complete(session, entity_type, entity_id, 0)
            return 0

        # Per-player checkpoint resume
        if not force:
            already_synced = self.bulk_already_indexed(
                "player_stats",
                [f"player_stats:{pid}:{season_id}" for pid in player_ids],
                max_age_hours=24,
            )
            if already_synced:
                before = len(player_ids)
                player_ids = [
                    pid for pid in player_ids
                    if f"player_stats:{pid}:{season_id}" not in already_synced
                ]
                logger.info(
                    "player_stats: skipping %d already-synced players (checkpoint resume), %d remaining",
                    before - len(player_ids), len(player_ids),
                )

        if not player_ids:
            with self.db_service.session_scope() as session:
                self._mark_sync_complete(session, entity_type, entity_id, 0)
            return 0

        logger.info("Indexing player stats for season %s%s (%d players)...", season_id, tier_lbl, len(player_ids))

        # ── Phase 1: parallel API fetches (no DB session held) ───────────────
        completed = 0
        _lock = threading.Lock()
        fetch_results: list[_PlayerStatsFetchResult] = []

        def _fetch_one(pid: int) -> _PlayerStatsFetchResult:
            nonlocal completed
            result = self._fetch_player_stats_raw(pid)
            with _lock:
                completed += 1
                if on_progress:
                    on_progress(int(completed / len(player_ids) * 80))
            return result

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(_fetch_one, pid): pid for pid in player_ids}
            for fut in as_completed(futures):
                try:
                    fetch_results.append(fut.result())
                except Exception as exc:
                    logger.warning("player_stats worker error: %s", exc)

        # ── Phase 2: batched DB writes ────────────────────────────────────────
        count = self._run_player_stats_phase2(
            fetch_results=fetch_results,
            season_id=season_id,
            season_label=season_label,
            entity_type=entity_type,
            entity_id=entity_id,
            exact_tier=exact_tier,
            now=now,
        )

        if on_progress:
            on_progress(100)
        logger.info("✓ Indexed %d player stat rows for season %s%s", count, season_id, tier_lbl)
        return count
```

Note: the outer `try/except Exception` block wrapping the old session is now gone. Errors propagate naturally (matching the player_game_stats pattern).

- [ ] **Step 4: Run all targeted tests**

```bash
.venv/bin/pytest tests/test_player_stats_phase2.py tests/test_player_stats_skip_logic.py tests/test_data_indexer_comprehensive.py -v
```

Expected: all pass

- [ ] **Step 5: Run full test suite**

```bash
.venv/bin/pytest -q --ignore=tests/test_api_endpoints.py
```

Expected: same pass/fail baseline (12 pre-existing failures, all others pass + new tests green)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/data_indexer.py backend/tests/test_player_stats_phase2.py
git commit -m "refactor(indexer): player_stats Phase 1/2 with ThreadPoolExecutor and checkpoint resume

Serial loop inside session_scope replaced with Phase 1 parallel API
fetches (ThreadPoolExecutor, 5 workers) and Phase 2 batched writes
(300 players/session). Eliminates session-held-during-API-calls
anti-pattern. Per-player checkpoint resume via bulk_already_indexed
means restarts skip already-written players."
```

---

## Final: Deploy and verify

- [ ] Push to remote and deploy to pi4desk

```bash
git push origin main
ssh pi4desk "cd /home/denny/dockerimages/SwissUnihockeyStats && git pull && docker build --no-cache -t swissunihockey:latest . && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --force-recreate"
```

- [ ] Enable scheduler in admin panel, trigger a player_game_stats run, confirm logs show new worker count

```bash
ssh pi4desk "docker logs swissunihockey-prod --follow 2>&1 | grep -E '(workers|player_stats|player_game_stats)'"
```

- [ ] Confirm no `database is locked` errors appear when multiple jobs run concurrently
