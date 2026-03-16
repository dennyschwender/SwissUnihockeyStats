# Local Per-Game Stats Backfill (T1–T3) — Design Spec

**Date:** 2026-03-16
**Status:** Approved

---

## Goal

Replace the `player_game_stats_t1/t2/t3` API jobs (7,400+ per-player API calls for T3 alone) with local derivation of `GamePlayer.goals`, `GamePlayer.assists`, and `GamePlayer.penalty_minutes` from already-stored `GameEvent` rows.

---

## Background

For T1/T2/T3 games with `completeness_status='complete'`:
- `GamePlayer` rows exist (from `game_lineups`) but have `goals=NULL`, `assists=NULL`, `penalty_minutes=NULL` — the lineup API does not provide per-game stats.
- `GameEvent` rows exist (from `post_game_completion`) with goal and penalty events including player name strings.
- The `player_game_stats_t1/t2/t3` jobs currently fill those NULL columns by calling `/api/players/{id}/overview` once per player — thousands of API calls that take minutes.

Since the data is already local, the API calls are redundant.

---

## What Changes

### Phase 0 added to `compute_player_stats_for_season`

A new function `backfill_game_player_stats_from_events(db_service, season_id, tiers)` in `local_stats_aggregator.py` runs as Phase 0 before the existing seasonal aggregation:

1. Queries all `complete` games in target tiers for the season.
2. For each game, fetches `GameEvent` rows and `GamePlayer` rows.
3. Parses goal events → scorer gets +1 goal, assister gets +1 assist.
4. Parses penalty events → penalized player gets penalty_minutes accumulated.
5. Name-matches players using `Player.first_name + last_name` (case-insensitive), same as existing `local_stats_aggregator.py` pattern.
6. Updates `GamePlayer.goals/assists/penalty_minutes` in DB.
7. Unresolved names → `UnresolvedPlayerEvent` (existing table/logic).

Only processes `GamePlayer` rows where `goals IS NULL` (skip already-backfilled games). Games with non-NULL goals (from a prior API run) are left untouched.

### Event Parsing

**Goal events** (`event_type` starts with `"Torschütze"` or `"Eigentor"`):
- `raw_data["player"]` after deduplication contains either `"ScorerName"` or `"ScorerName / AssistName"`.
- Split on `" / "` to extract scorer (index 0) and optional assister (index 1).
- Scorer gets `+1 goal`; assister gets `+1 assist`.
- Own goals (`"Eigentor"`): scorer gets +1 goal, no assist.

**Penalty events** (`event_type` contains `"'-Strafe"`):
- `raw_data["player"]` is the penalized player's name.
- pim is derived from event_type via existing `_pen_bucket()` → 2/5/10/match minutes.

### Scheduler

Remove `player_game_stats_t1`, `player_game_stats_t2`, `player_game_stats_t3` from `POLICIES` in `scheduler.py`. T4/T5/T6 `player_game_stats` policies remain unchanged and continue using the API.

### DataIndexer

`compute_player_stats_for_season` calls `backfill_game_player_stats_from_events` before calling `aggregate_player_stats_for_season`. The backfill result (rows updated) is included in the log output.

In `index_player_game_stats_for_season`, add a guard for tiers 1–3 (same pattern as the existing guard in `index_player_stats_for_season`) — return 0 immediately and mark SyncStatus complete.

---

## Schema

No changes. `GamePlayer.goals/assists/penalty_minutes` already exist and are nullable.

---

## Out of Scope

- T4/T5/T6 per-game stats (no events indexed for those tiers)
- Retroactive backfill for past seasons (current season only, same as `compute_player_stats`)
- Backfill for `post_game` games (only `complete` games)

---

## Success Criteria

1. `player_game_stats_t1/t2/t3` scheduler jobs no longer exist.
2. `GamePlayer.goals/assists/penalty_minutes` are populated for all T1–T3 complete games within one `compute_player_stats` cycle.
3. `PlayerStatistics` seasonal aggregates (goals/assists/pim) are correct — same values as before, now derived locally.
4. No regressions in existing tests.
