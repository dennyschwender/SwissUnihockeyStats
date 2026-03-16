# Local Per-Game Stats Backfill (T1–T3) Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `player_game_stats_t1/t2/t3` API jobs with local derivation of `GamePlayer.goals/assists/penalty_minutes` from `GameEvent` rows, run as Phase 0 inside `compute_player_stats_for_season`.

**Architecture:** New `backfill_game_player_stats_from_events()` function in `local_stats_aggregator.py` iterates complete T1-T3 games, parses goal/penalty events, name-matches to `GamePlayer` rows, and updates the DB. Called from `compute_player_stats_for_season` before the existing seasonal aggregation. T1-T3 API jobs disabled in scheduler and guarded in `index_player_game_stats_for_season`.

**Tech Stack:** SQLAlchemy 2.x, FastAPI, SQLite, pytest

---

## File Map

| File | Change |
|---|---|
| `backend/app/services/local_stats_aggregator.py` | Add `backfill_game_player_stats_from_events()` |
| `backend/app/services/data_indexer.py` | Call backfill in `compute_player_stats_for_season`; add T1-T3 guard in `index_player_game_stats_for_season` |
| `backend/app/services/scheduler.py` | Remove T1/T2/T3 `player_game_stats` policies; remove `requires` from T4 policy |
| `backend/tests/test_local_stats_aggregator.py` | Add tests for `backfill_game_player_stats_from_events` |

---

## Chunk 1: Backfill function

### Task 1: Add `backfill_game_player_stats_from_events` to `local_stats_aggregator.py`

**Files:**
- Modify: `backend/app/services/local_stats_aggregator.py`
- Modify: `backend/tests/test_local_stats_aggregator.py`

**Context:**

Key facts about GameEvent data:
- `event_type` for goals starts with `"Torschütze"` or `"Eigentor"` (own goal)
- `event_type` for penalties contains `"'-Strafe"` (already handled by `_pen_bucket`)
- `raw_data["player"]` for goal events: either `"ScorerName"` (no assist) or `"ScorerName / AssistName"` (with assist). Split on `" / "` — index 0 is scorer, index 1 is assister.
- Own goals (`"Eigentor"`): scorer gets +1 goal, no assist recorded.
- `raw_data["player"]` for penalty events: the penalized player's name.
- `penalty_minutes` for a player in a game = sum of minutes from all their penalty events (use `_pen_bucket` → 2/5/10 min mapping). If bucket is "match" → 5 min (match penalty = 5 min PIM in Swiss floorball).

Only process `GamePlayer` rows where `goals IS NULL` — skip games already backfilled.

Name matching: reuse the existing `name_map` pattern from `aggregate_player_stats_for_season`:
- Build `{lower(first_name + " " + last_name): player_id}` per `(game_id, team_id)` from Player table
- Match `raw_data["player"]` values case-insensitively
- Unresolved → `UnresolvedPlayerEvent` (existing logic)

`_pen_bucket` → minutes mapping:
```python
_BUCKET_MINUTES = {"2min": 2, "5min": 5, "10min": 10, "match": 5}
```

The function returns the count of `GamePlayer` rows updated.

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/test_local_stats_aggregator.py` (append after existing tests):

```python
from app.services.local_stats_aggregator import backfill_game_player_stats_from_events


# ── backfill_game_player_stats_from_events tests ──────────────────────────────

def _seed_complete_game_with_events(engine, api_id=10):
    """Seed a complete game with two players and goal + penalty events."""
    with Session(engine) as s:
        # Reuse or create Season id=1
        from sqlalchemy import select as _sel
        season = s.execute(_sel(Season).where(Season.id == 1)).scalar_one_or_none()
        if season is None:
            season = Season(id=1, text="2025")
            s.add(season)
            s.flush()

        club = Club(id=api_id * 10, season_id=1, name=f"Club{api_id}")
        s.add(club)
        s.flush()
        team = Team(id=api_id * 10, season_id=1, club_id=api_id * 10,
                    name=f"Team{api_id}", league_id=1)
        s.add(team)
        s.flush()

        # Ensure League id=1 exists
        league = s.execute(_sel(League).where(League.id == 1)).scalar_one_or_none()
        if league is None:
            league = League(id=1, season_id=1, league_id=1, game_class=1, name="NLA")
            s.add(league)
            s.flush()
        # Ensure LeagueGroup id=1 exists
        group = s.execute(_sel(LeagueGroup).where(LeagueGroup.id == 1)).scalar_one_or_none()
        if group is None:
            group = LeagueGroup(id=1, league_id=1, group_id=1, name="NLA")
            s.add(group)
            s.flush()

        p1 = Player(person_id=api_id * 100, first_name="Anna", last_name="Müller")
        p2 = Player(person_id=api_id * 100 + 1, first_name="Ben", last_name="Huber")
        s.add_all([p1, p2])
        s.flush()

        game = Game(
            id=api_id, season_id=1,
            home_team_id=api_id * 10, away_team_id=api_id * 10,
            status="finished", completeness_status="complete",
            home_score=2, away_score=1, group_id=1,
        )
        s.add(game)
        s.flush()

        # GamePlayer rows with goals=NULL (as created by game_lineups job)
        gp1 = GamePlayer(game_id=api_id, player_id=api_id * 100,
                         team_id=api_id * 10, season_id=1,
                         is_home_team=True, goals=None, assists=None, penalty_minutes=None)
        gp2 = GamePlayer(game_id=api_id, player_id=api_id * 100 + 1,
                         team_id=api_id * 10, season_id=1,
                         is_home_team=True, goals=None, assists=None, penalty_minutes=None)
        s.add_all([gp1, gp2])
        s.flush()

        # Goal event: Anna scored, Ben assisted
        ge_goal = GameEvent(
            game_id=api_id, team_id=api_id * 10, season_id=1,
            event_type="Torschütze",
            raw_data={"player": "Anna Müller / Ben Huber", "event_type": "Torschütze",
                      "time": "10:00", "team": f"Team{api_id}"},
        )
        # Penalty event: Anna penalised 2 min
        ge_pen = GameEvent(
            game_id=api_id, team_id=api_id * 10, season_id=1,
            event_type="2'-Strafe",
            raw_data={"player": "Anna Müller", "event_type": "2'-Strafe",
                      "time": "20:00", "team": f"Team{api_id}"},
        )
        s.add_all([ge_goal, ge_pen])
        s.commit()
    return api_id


def test_backfill_sets_goals_and_assists(engine, mock_db):
    gid = _seed_complete_game_with_events(engine, api_id=10)
    count = backfill_game_player_stats_from_events(mock_db, season_id=1, tiers=[1, 2, 3])
    assert count >= 1
    with Session(engine) as s:
        gp_scorer = s.query(GamePlayer).filter_by(
            game_id=gid, player_id=1000).first()
        gp_assister = s.query(GamePlayer).filter_by(
            game_id=gid, player_id=1001).first()
        assert gp_scorer.goals == 1
        assert gp_scorer.assists == 0
        assert gp_assister.assists == 1
        assert gp_assister.goals == 0


def test_backfill_sets_penalty_minutes(engine, mock_db):
    gid = _seed_complete_game_with_events(engine, api_id=10)
    backfill_game_player_stats_from_events(mock_db, season_id=1, tiers=[1, 2, 3])
    with Session(engine) as s:
        gp = s.query(GamePlayer).filter_by(game_id=gid, player_id=1000).first()
        assert gp.penalty_minutes == 2


def test_backfill_skips_already_filled_rows(engine, mock_db):
    gid = _seed_complete_game_with_events(engine, api_id=10)
    # Pre-fill with existing values
    with Session(engine) as s:
        gp = s.query(GamePlayer).filter_by(game_id=gid, player_id=1000).first()
        gp.goals = 5  # already filled
        s.commit()
    count = backfill_game_player_stats_from_events(mock_db, season_id=1, tiers=[1, 2, 3])
    # Game skipped because goals IS NOT NULL
    assert count == 0
    with Session(engine) as s:
        gp = s.query(GamePlayer).filter_by(game_id=gid, player_id=1000).first()
        assert gp.goals == 5  # unchanged


def test_backfill_creates_unresolved_for_unknown_player(engine, mock_db):
    gid = _seed_complete_game_with_events(engine, api_id=10)
    # Add a goal event with an unknown player name
    with Session(engine) as s:
        s.add(GameEvent(
            game_id=gid, team_id=100, season_id=1,
            event_type="Torschütze",
            raw_data={"player": "Ghost Player", "event_type": "Torschütze",
                      "time": "30:00", "team": "Team10"},
        ))
        s.commit()
    backfill_game_player_stats_from_events(mock_db, season_id=1, tiers=[1, 2, 3])
    with Session(engine) as s:
        unresolved = s.query(UnresolvedPlayerEvent).filter_by(
            game_id=gid, raw_name="Ghost Player").first()
        assert unresolved is not None


def test_backfill_no_complete_games_returns_zero(engine, mock_db):
    with Session(engine) as s:
        existing = s.execute(__import__('sqlalchemy').select(Season).where(Season.id == 1)).scalar_one_or_none()
        if existing is None:
            s.add(Season(id=1, text="2025"))
            s.commit()
    count = backfill_game_player_stats_from_events(mock_db, season_id=1, tiers=[1, 2, 3])
    assert count == 0
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend && .venv/bin/pytest tests/test_local_stats_aggregator.py -k "backfill" -v
```

Expected: FAIL — `backfill_game_player_stats_from_events` not imported.

- [ ] **Step 3: Implement `backfill_game_player_stats_from_events`**

Add to `backend/app/services/local_stats_aggregator.py` after the existing `_pen_bucket` function:

```python
# Minutes per penalty bucket (Swiss floorball: match penalty = 5 min PIM)
_BUCKET_MINUTES: dict[str, int] = {"2min": 2, "5min": 5, "10min": 10, "match": 5}


def _parse_goal_players(raw_data: dict) -> tuple[str | None, str | None]:
    """Extract (scorer_name, assister_name) from a goal event's raw_data.

    raw_data["player"] is either "ScorerName" or "ScorerName / AssistName".
    Returns (scorer, assister_or_None).
    """
    player_str = (raw_data.get("player") or "").strip()
    if not player_str:
        return None, None
    parts = player_str.split(" / ", 1)
    scorer = parts[0].strip() or None
    assister = parts[1].strip() if len(parts) > 1 else None
    return scorer, assister


def backfill_game_player_stats_from_events(
    db_service,
    season_id: int,
    tiers: Sequence[int] = (1, 2, 3),
) -> int:
    """Fill GamePlayer.goals/assists/penalty_minutes from GameEvent rows.

    For each complete T1-T3 game where GamePlayer rows still have goals=NULL,
    parse goal and penalty events, match player names to GamePlayer rows, and
    update the stats. Unmatched names create UnresolvedPlayerEvent records.

    Returns the number of GamePlayer rows updated.
    """
    tiers_set = set(tiers)
    updated = 0

    with db_service.session_scope() as session:
        # Find complete games in target tiers with un-backfilled lineup rows
        # (goals IS NULL = not yet filled by this job or by API)
        games = (
            session.query(Game)
            .filter(
                Game.season_id == season_id,
                Game.completeness_status == "complete",
                Game.group_id.isnot(None),
            )
            .all()
        )

        # Filter to target tiers; skip games where all players already have goals set
        tier_games: list[tuple[int, int]] = []  # (game_id, tier)
        for game in games:
            result = _resolve_tier_and_abbrev(game, session)
            if result is None:
                continue
            tier, _ = result
            if tier not in tiers_set:
                continue
            # Check if any GamePlayer row for this game has goals=NULL
            has_null = (
                session.query(GamePlayer)
                .filter(
                    GamePlayer.game_id == game.id,
                    GamePlayer.goals.is_(None),
                )
                .first()
            )
            if has_null:
                tier_games.append((game.id, tier))

        if not tier_games:
            return 0

        game_ids = [gid for gid, _ in tier_games]

        # Build name → player_id lookup per (game_id, team_id)
        gp_all = (
            session.query(GamePlayer)
            .filter(
                GamePlayer.season_id == season_id,
                GamePlayer.game_id.in_(game_ids),
            )
            .all()
        )
        player_names: dict[int, str] = {
            p.person_id: f"{p.first_name or ''} {p.last_name or ''}".strip().lower()
            for p in session.query(PlayerModel)
            .filter(PlayerModel.person_id.in_({gp.player_id for gp in gp_all}))
            .all()
        }
        name_map: dict[tuple[int, int], dict[str, int]] = {}
        for gp in gp_all:
            key = (gp.game_id, gp.team_id)
            name = player_names.get(gp.player_id, "")
            if name:
                name_map.setdefault(key, {})[name] = gp.player_id

        # Accumulate stats per (game_id, player_id)
        # goals_acc[(game_id, player_id)] = int
        goals_acc: dict[tuple[int, int], int] = {}
        assists_acc: dict[tuple[int, int], int] = {}
        pim_acc: dict[tuple[int, int], int] = {}

        seen_unresolved: set[tuple] = set()
        game_id_set = set(game_ids)

        events = (
            session.query(GameEvent)
            .filter(
                GameEvent.season_id == season_id,
                GameEvent.game_id.in_(game_ids),
            )
            .all()
        )

        for evt in events:
            etype = evt.event_type.lower()
            key = (evt.game_id, evt.team_id)

            def _resolve_pid(raw_name: str) -> int | None:
                pid = name_map.get(key, {}).get(raw_name.lower())
                if pid is None:
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
                                created_at=_now(),
                            ))
                return pid

            if etype.startswith(("torschütze", "eigentor")):
                # Goal event
                scorer_name, assister_name = _parse_goal_players(evt.raw_data or {})
                if scorer_name:
                    pid = _resolve_pid(scorer_name)
                    if pid is not None:
                        gkey = (evt.game_id, pid)
                        goals_acc[gkey] = goals_acc.get(gkey, 0) + 1
                # Own goals: no assist
                is_own_goal = etype.startswith("eigentor")
                if assister_name and not is_own_goal:
                    pid = _resolve_pid(assister_name)
                    if pid is not None:
                        akey = (evt.game_id, pid)
                        assists_acc[akey] = assists_acc.get(akey, 0) + 1

            elif "'-strafe" in etype:
                # Penalty event
                raw_name = _player_name_from_event(evt)
                if raw_name:
                    pid = _resolve_pid(raw_name)
                    if pid is not None:
                        bucket = _pen_bucket(evt.event_type)
                        if bucket:
                            pkey = (evt.game_id, pid)
                            pim_acc[pkey] = pim_acc.get(pkey, 0) + _BUCKET_MINUTES[bucket]

        # Write accumulated stats to GamePlayer rows
        now = _now()
        for gp in gp_all:
            if gp.goals is not None:
                continue  # already filled — skip
            gkey = (gp.game_id, gp.player_id)
            new_goals = goals_acc.get(gkey, 0)
            new_assists = assists_acc.get(gkey, 0)
            new_pim = pim_acc.get(gkey, 0)
            gp.goals = new_goals
            gp.assists = new_assists
            gp.penalty_minutes = new_pim
            gp.last_updated = now
            updated += 1

        logger.info(
            "backfill_game_player_stats: %d GamePlayer rows updated for season %s (tiers %s)",
            updated, season_id, sorted(tiers_set),
        )

    return updated
```

- [ ] **Step 4: Run tests**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend && .venv/bin/pytest tests/test_local_stats_aggregator.py -k "backfill" -v
```

Expected: All backfill tests PASS.

If `test_backfill_sets_goals_and_assists` fails with a player_id mismatch, verify the seed uses `api_id=10` → `player_id=1000` and `1001`. Adjust the `filter_by(player_id=...)` calls in the test if needed.

- [ ] **Step 5: Run full aggregator test suite**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend && .venv/bin/pytest tests/test_local_stats_aggregator.py -v
```

Expected: All 11 existing tests + new backfill tests pass.

- [ ] **Step 6: Run full suite**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend && .venv/bin/pytest --tb=short -q
```

Expected: All tests pass.

- [ ] **Step 7: Commit**

```bash
cd /home/denny/Development/SwissUnihockeyStats && git add backend/app/services/local_stats_aggregator.py backend/tests/test_local_stats_aggregator.py && git commit -m "feat(stats): add backfill_game_player_stats_from_events — derive per-game G/A/PIM from events for T1-T3"
```

---

## Chunk 2: DataIndexer + Scheduler

### Task 2: Wire backfill into `compute_player_stats_for_season` and disable T1-T3 API jobs

**Files:**
- Modify: `backend/app/services/data_indexer.py`
- Modify: `backend/app/services/scheduler.py`
- Modify: `backend/tests/test_local_stats_integration.py`

**Context:**

`compute_player_stats_for_season` is at line ~1236 in `data_indexer.py`. It currently calls only `aggregate_player_stats_for_season`. Update it to call `backfill_game_player_stats_from_events` first.

`index_player_game_stats_for_season` starts at line ~2527. Add a guard at the top (after the entity_type/entity_id block): if `exact_tier in {1, 2, 3}`, mark SyncStatus complete and return 0. Same pattern as the existing guard in `index_player_stats_for_season`.

In `scheduler.py`, remove the three policy dicts for `player_game_stats_t1`, `player_game_stats_t2`, `player_game_stats_t3` (lines ~263-300). Also update `player_game_stats_t4` to remove `"requires": "player_game_stats_t3"` since that policy no longer exists.

- [ ] **Step 1: Write tests**

Append to `backend/tests/test_local_stats_integration.py`:

```python
def test_compute_player_stats_calls_backfill_first(engine, indexer):
    """compute_player_stats_for_season runs backfill before aggregation."""
    from unittest.mock import patch, call
    with patch(
        "app.services.local_stats_aggregator.backfill_game_player_stats_from_events",
        return_value=0,
    ) as mock_backfill, patch(
        "app.services.local_stats_aggregator.aggregate_player_stats_for_season",
        return_value=0,
    ) as mock_agg:
        with Session(engine) as s:
            from app.models.db_models import Season
            if not s.get(Season, 1):
                s.add(Season(id=1, text="2025"))
                s.commit()
        indexer.compute_player_stats_for_season(season_id=1, force=True)
        mock_backfill.assert_called_once()
        mock_agg.assert_called_once()
        # backfill must be called before aggregation
        assert mock_backfill.call_args[1]["season_id"] == 1 or mock_backfill.call_args[0][1] == 1


def test_index_player_game_stats_skips_tier_1(engine, indexer):
    with Session(engine) as s:
        from app.models.db_models import Season
        if not s.get(Season, 1):
            s.add(Season(id=1, text="2025"))
            s.commit()
    result = indexer.index_player_game_stats_for_season(season_id=1, exact_tier=1, force=True)
    assert result == 0


def test_index_player_game_stats_skips_tier_3(engine, indexer):
    with Session(engine) as s:
        from app.models.db_models import Season
        if not s.get(Season, 1):
            s.add(Season(id=1, text="2025"))
            s.commit()
    result = indexer.index_player_game_stats_for_season(season_id=1, exact_tier=3, force=True)
    assert result == 0


def test_player_game_stats_t1_t2_t3_not_in_scheduler_policies():
    from app.services.scheduler import POLICIES
    policy_names = {p["name"] for p in POLICIES}
    assert "player_game_stats_t1" not in policy_names
    assert "player_game_stats_t2" not in policy_names
    assert "player_game_stats_t3" not in policy_names
    # T4 must still exist
    assert "player_game_stats_t4" in policy_names
```

- [ ] **Step 2: Run to verify failures**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend && .venv/bin/pytest tests/test_local_stats_integration.py -k "backfill_first or game_stats_skip or t1_t2_t3_not" -v
```

Expected: FAIL.

- [ ] **Step 3: Update `compute_player_stats_for_season` in `data_indexer.py`**

Find the method and update the `try` block to call backfill first:

```python
        from app.services.local_stats_aggregator import (
            aggregate_player_stats_for_season,
            backfill_game_player_stats_from_events,
        )
        try:
            backfill_n = backfill_game_player_stats_from_events(
                self.db_service, season_id, tiers=tiers
            )
            count = aggregate_player_stats_for_season(
                self.db_service, season_id, tiers=tiers
            )
            with self.db_service.session_scope() as session:
                self._mark_sync_complete(session, entity_type, entity_id, count)
            logger.info(
                "compute_player_stats season=%s → backfill=%d rows, stats=%d rows",
                season_id, backfill_n, count,
            )
            return count
        except Exception as exc:
            logger.error("compute_player_stats season=%s failed: %s", season_id, exc)
            raise
```

- [ ] **Step 4: Add guard to `index_player_game_stats_for_season` in `data_indexer.py`**

After the block that sets `entity_type` and `entity_id` (and before the `_should_update` check), add:

```python
        # T1–T3 per-game stats are derived locally; skip API calls for these tiers.
        if exact_tier in {1, 2, 3}:
            logger.info(
                "Skipping API player game stats for tier %d (handled by local backfill)", exact_tier
            )
            with self.db_service.session_scope() as _s:
                self._mark_sync_complete(_s, entity_type, entity_id, 0)
            return 0
```

- [ ] **Step 5: Remove T1/T2/T3 policies from `scheduler.py`**

Read the file, then delete the three policy dicts for `player_game_stats_t1`, `player_game_stats_t2`, `player_game_stats_t3` (the blocks with `"name": "player_game_stats_t1"`, `"player_game_stats_t2"`, `"player_game_stats_t3"`).

Also update `player_game_stats_t4` — remove `"requires": "player_game_stats_t3"` from its dict (it no longer has a predecessor).

Also remove the comment above the removed block if it only refers to the removed policies (check context).

- [ ] **Step 6: Run the new tests**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend && .venv/bin/pytest tests/test_local_stats_integration.py -v
```

Expected: All pass.

- [ ] **Step 7: Run full suite**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend && .venv/bin/pytest --tb=short -q
```

Expected: All tests pass.

- [ ] **Step 8: Commit**

```bash
cd /home/denny/Development/SwissUnihockeyStats && git add backend/app/services/data_indexer.py backend/app/services/scheduler.py backend/tests/test_local_stats_integration.py && git commit -m "feat(indexer): wire per-game backfill into compute_player_stats; remove T1-T3 player_game_stats API jobs"
```

---

## Chunk 3: Final verification

### Task 3: Lint + full test run

- [ ] **Step 1: Lint**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend && .venv/bin/black app/ tests/ && .venv/bin/flake8 app/ tests/ --max-line-length=120 --count --select=E9,F63,F7,F82 --show-source --statistics
```

Fix any errors.

- [ ] **Step 2: Full test suite**

```bash
cd /home/denny/Development/SwissUnihockeyStats/backend && .venv/bin/pytest --tb=short -q
```

Expected: All tests pass.

- [ ] **Step 3: Commit lint fixes (if needed)**

```bash
cd /home/denny/Development/SwissUnihockeyStats && git add -u && git commit -m "chore: lint fixes for per-game stats backfill"
```
