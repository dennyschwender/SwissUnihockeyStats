# Past Season Games Indexing Design

**Date:** 2026-03-30
**Status:** Approved

## Problem

When old seasons are added to the DB (e.g. via gap detection for `min_season=2018`), the scheduler correctly indexes clubs, teams, leagues, and players for those seasons. However, **games, game events, and game lineups are never indexed** for past seasons because:

1. The only game indexing policy (`upcoming_games`) has `current_only: True` — it only runs for the current season.
2. There is no scheduler policy for `games`, `game_events`, or `game_lineups` covering past seasons.

Result: seasons like 2018/2019/2020 end up with clubs/leagues/players but zero games, making their data largely useless for the stats pages.

## Goal

All seasons within `[min_season, current_season]` should have the same data: clubs, teams, leagues, **games, game events, and game lineups**. The scheduler should index missing data automatically without manual CLI intervention.

## Design

### Part 1: New `past_only` flag

Add a `past_only: True` flag (the inverse of the existing `current_only: True`) to policies that should only run for past seasons.

One new guard in `_maybe_schedule` in `scheduler.py`:

```python
if policy.get("past_only") and is_current_season:
    return
```

This ensures current-season game indexing stays owned by `upcoming_games` and `post_game_completion` — no overlap with the new policies.

### Part 2: Two new policies in `POLICIES`

Add after the existing `leagues` policy (priority 50), before `upcoming_games_noon` (priority 70):

```python
{
    "name": "games",
    "entity_type": "games",
    "task": "games",           # runs leagues → league_groups → games → team_names
    "scope": "season",
    "past_only": True,
    "requires": "leagues",     # wait until leagues are indexed for this season
    "label": "Games (past seasons)",
    "max_age": timedelta(days=7),
    "priority": 55,
    "run_at_hour": 3,
},
{
    "name": "game_events",
    "entity_type": "game_events",
    "task": "events",          # runs game_events + game_lineups together
    "scope": "season",
    "past_only": True,
    "requires": "games",       # wait until games are indexed for this season
    "label": "Game events + lineups (past seasons)",
    "max_age": timedelta(days=7),
    "priority": 60,
    "run_at_hour": 3,
},
```

**Why `task="games"` also re-runs leagues/groups:** The `games` task in `main.py` runs the full `leagues → league_groups → games → team_names` pipeline. Re-running `index_leagues` and `index_groups_for_league` for a past season is idempotent and cheap — no harm.

**Sentinel writes (already in place):**
- `task="games"` → writes `league_groups` sentinel (main.py:2325) and `games` sentinel (main.py:2383) ✓
- `task="events"` → writes `game_events` sentinel (main.py:2495) ✓

Note: `task="events"` processes both game events and game lineups in a single pass (main.py:2474-2476). The `game_events` sentinel is sufficient to gate re-runs for both.

### Part 3: Policy chain

```
clubs(20) → teams(30) → players(40) → leagues(50)
                                          └── games(55, past_only, requires=leagues)
                                                └── game_events(60, past_only, requires=games)
```

The `requires` field in each policy maps to an `entity_type` checked via `_last_sync_for`. Because sentinels are written at the season level, the prerequisite gate works correctly across ticks.

### Part 4: Interaction with existing freeze logic

**"Frozen once indexed" (line 1009):**
```python
if not is_current_season and last_sync is not None:
    return
```
Once `games` is indexed for season 2019, the `games` policy won't fire again. Same for `game_events`. ✓

**`is_frozen` skip (line 970):**
Frozen seasons are skipped entirely before any policy check. The new policies respect this — no change needed. ✓

**Auto-freeze (`_is_season_complete`):**
Requires `total games > 0`. Before `games` runs, total=0 → no premature freeze. After games are indexed and all have `status in ('finished', 'cancelled')` → auto-freeze triggers and stops all further jobs. ✓

## Scope

- `scheduler.py`: add `past_only` guard in `_maybe_schedule` (~2 lines), add 2 policy dicts to `POLICIES`
- `main.py`: no changes needed — `task="games"` and `task="events"` already handle the dispatch correctly
- No DB model changes
- No admin UI changes

## Out of Scope

- Separate `game_lineups` policy — covered by `task="events"` which runs lineups in the same pass
- Separate `league_groups` policy — covered by `task="games"` which runs groups as a sub-step
- Backfilling seasons prior to `min_season` — those are filtered by `_season_filtered`
