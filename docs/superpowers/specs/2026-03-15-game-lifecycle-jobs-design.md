# Game Lifecycle Jobs — Design Spec

**Date:** 2026-03-15
**Status:** Approved

---

## Problem

The current scheduler polls all game-related data on fixed schedules regardless of whether a game is truly complete:

- `games` — nightly, fetches schedule metadata for all games in a season
- `game_lineups` — every 24 h, fetches rosters for all games (NLA/NLB only)
- `game_events` — every 10 min, fetches score/goals/penalties/referees for all games; uses an age-based TTL (`_game_events_ttl_hours`) to slow down over time but never stops

There is no concept of a game being *permanently done*. Old finished games keep being polled forever, wasting API budget and DB writes.

---

## Goal

- **Upcoming games** (not yet played): poll 3× per day for schedule changes (time, referees, venue).
- **Finished games**: poll until all required fields are populated for that tier, then mark as `complete` and never poll again.
- **Give-up rule**: if a finished game is still incomplete after ~3 days from its `game_date`, mark it `abandoned` and log it to a failure table. Admin can inspect and trigger a manual retry.
- **Live games**: out of scope for now — treated as upcoming until the API flips them to `finished`. This means a game finishing at ~22:00 may not enter post-game processing until the 23:00 UTC tick (~50 min delay vs. the current 10-min interval). Acceptable for this phase.

---

## Data Model Changes

### New columns on `Game`

| Column | Type | Default | Purpose |
|---|---|---|---|
| `completeness_status` | String | `upcoming` | Lifecycle state: `upcoming` / `post_game` / `complete` / `abandoned` |
| `incomplete_fields` | JSON | null | List of still-missing field names, e.g. `["events", "lineup", "referees"]`. Null for `upcoming` and `complete` games. |
| `give_up_at` | DateTime (UTC) | null | Set to `game_date + 3 days` (UTC) when game flips to `post_game`. When `utcnow() > give_up_at` → abandon. |
| `completeness_checked_at` | DateTime (UTC) | null | Updated on **every** completeness check attempt (complete, incomplete, and abandoned), enabling debugging of stuck games. |

Add index: `Index('idx_game_completeness_status', 'completeness_status')` to support scheduler queries.

All datetimes use UTC via the existing `_utcnow()` helper. `game_date` is already stored in UTC.

### New table: `GameSyncFailure`

| Column | Type | Purpose |
|---|---|---|
| `id` | Integer PK | — |
| `game_id` | FK → Game | The incomplete game |
| `season_id` | Integer | Denormalized for easy admin filtering (no FK constraint, consistent with other denormalized season_id columns) |
| `abandoned_at` | DateTime (UTC) | When we gave up |
| `missing_fields` | JSON | Fields that were still missing at abandon time |
| `can_retry` | Boolean | Admin flips to `True` to queue a manual retry |
| `retried_at` | DateTime (UTC) | Null until a retry is attempted |

**On retry failure**: if a retried game goes `abandoned` again, the existing `GameSyncFailure` row is updated (`can_retry = False`, new `abandoned_at`, updated `missing_fields`) rather than creating a duplicate row. The `retried_at` timestamp records when the retry was attempted.

### Startup migration

Run idempotently on every app start (existing pattern). Uses `_utcnow()` for all timestamp comparisons:

1. `status = "finished"` + already complete (has score + required events/lineup per tier) → `complete`, `incomplete_fields = null`
2. `status = "finished"` + incomplete + `game_date + 3 days > utcnow()` → `post_game`, `give_up_at = game_date + 3 days`, `incomplete_fields = [missing fields]`
3. `status = "finished"` + incomplete + `game_date + 3 days <= utcnow()` (old games with missing data) → `abandoned`, write `GameSyncFailure` row
4. All other games (`scheduled`, `live`) → `upcoming`, `incomplete_fields = null`

**Defensive rule**: any game with `status = "finished"` and `completeness_status = "upcoming"` (e.g. missed tick, restart) is treated as `post_game` by the jobs without waiting for the next migration run.

---

## Tier Resolution

`_is_game_complete` requires a `tier` for the game. Tier is resolved by the **caller** before invoking the function, using the following join chain:

```
Game.group_id → LeagueGroup (id) → LeagueGroup.league_id (FK) → League (id) → League.league_id (API ID) → LEAGUE_TIERS[league_id]
```

`LEAGUE_TIERS` already exists in `data_indexer.py` and maps API `league_id` → tier int (1–6).

**Fallback**: if `game.group_id` is null (can happen for newly scraped games not yet fully indexed), default to tier `6` (most conservative: requires only `score`). This ensures the game can still be marked complete rather than blocked indefinitely.

---

## Completeness Check

### `TIER_COMPLETENESS_FIELDS` config

Lives in a new `services/game_completeness.py` module. Updated empirically as each league's API coverage is confirmed by testing — no logic changes required when updating, only config.

```python
TIER_COMPLETENESS_FIELDS: dict[int, set[str]] = {
    1: {"score", "referees", "spectators", "events", "lineup", "best_players"},
    2: {"score", "referees", "spectators", "events", "lineup", "best_players"},
    3: {"score"},  # to be confirmed by testing
    4: {"score"},  # to be confirmed by testing
    5: {"score"},  # to be confirmed by testing
    6: {"score"},  # to be confirmed by testing
}
```

Unknown tiers fall back to `{"score"}`.

### `_is_game_complete(game, tier, session) → tuple[bool, list[str]]`

Returns `(is_complete, missing_fields)`. Only fields listed in `TIER_COMPLETENESS_FIELDS[tier]` are checked.

| Field key | Check |
|---|---|
| `score` | `home_score` and `away_score` are not null |
| `referees` | `referee_1` is not null |
| `spectators` | `spectators` is not null |
| `events` | at least 1 `GameEvent` row for this game (any type except `best_player`) |
| `lineup` | at least 1 `GamePlayer` row for this game |
| `best_players` | at least 1 `GameEvent` row with `event_type = "best_player"` for this game (API sometimes returns only 1; threshold is ≥1 not exactly 2) |

**Note**: `best_players` are stored as `GameEvent` rows with `event_type = "best_player"`, not in a separate table.

---

## Scheduler Jobs

Both jobs follow the existing single-job-iterates-all-targets pattern (like the current `game_events` job), not one-job-per-game. This respects the `max_concurrent = 2` constraint.

### Job 1: `upcoming_games`

| Property | Value |
|---|---|
| Triggers | 12:00, 18:00, 23:00 UTC daily |
| Target | Games where `completeness_status = 'upcoming'` **or** (`status = 'finished'` and `completeness_status = 'upcoming'`) |
| Fetches | Game metadata: date, time, teams, venue, pre-assigned referees |
| On `status = "finished"` from API | Flip to `post_game`, set `give_up_at = game_date + 3 days`, set `incomplete_fields` |

### Job 2: `post_game_completion`

| Property | Value |
|---|---|
| Triggers | Every 2 hours |
| Target | Games where `completeness_status = 'post_game'` |
| Fetches | Tier-aware: events, lineup, score details, referees, spectators, best players |

After each fetch, resolve tier via the join chain above, then call `_is_game_complete()`. Update `completeness_checked_at` on every attempt.

| Outcome | Action |
|---|---|
| Complete | Flip to `complete`, clear `incomplete_fields` |
| Incomplete, `utcnow() < give_up_at` | Update `incomplete_fields`, retry next tick |
| Incomplete, `utcnow() >= give_up_at` | Flip to `abandoned`, write/update `GameSyncFailure` row |

### Manual retry (admin)

Admin sets `GameSyncFailure.can_retry = True` via admin panel. On next `post_game_completion` tick:

1. Detect `GameSyncFailure` rows where `can_retry = True`
2. Reset game to `post_game`, set `give_up_at = utcnow() + 3 days`, clear `incomplete_fields`
3. Set `GameSyncFailure.retried_at = utcnow()`, `can_retry = False`

---

## What Gets Removed

- `_game_events_ttl_hours()` — age-based TTL function (replaced by lifecycle state)
- Scheduler policies: `games`, `game_lineups`, `game_events` — replaced by the two new jobs above

---

## Testing Strategy

1. **Unit tests for `_is_game_complete`**: each field check, each tier, correct missing-fields list returned.
2. **Unit tests for tier resolution**: null `group_id` falls back to tier 6; normal chain resolves correctly.
3. **Unit tests for state transitions**: upcoming → post_game on finish; post_game → complete; post_game → abandoned past deadline; abandoned → post_game on manual retry.
4. **Retry idempotency test**: second failure updates existing `GameSyncFailure` row, does not create a duplicate.
5. **Migration test**: seed DB with finished games in various states, assert correct `completeness_status` assigned.
6. **Empirical tier mapping**: run `post_game_completion` against each real league and observe which fields populate — update `TIER_COMPLETENESS_FIELDS` accordingly.
