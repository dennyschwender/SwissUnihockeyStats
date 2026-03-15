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
- **Give-up rule**: if a finished game is still incomplete after ~3 days, mark it `abandoned` and log it to a failure table. Admin can inspect and trigger a manual retry.
- **Live games**: out of scope for now — treated as upcoming until the API flips them to `finished`.

---

## Data Model Changes

### New columns on `Game`

| Column | Type | Default | Purpose |
|---|---|---|---|
| `completeness_status` | String | `upcoming` | Lifecycle state: `upcoming` / `post_game` / `complete` / `abandoned` |
| `incomplete_fields` | JSON | null | List of still-missing field names, e.g. `["events", "lineup", "referees"]` |
| `give_up_at` | DateTime | null | Set when game flips to `post_game` (`game_date + 3 days`). When passed → abandon. |
| `completeness_checked_at` | DateTime | null | Timestamp of the last completeness check |

### New table: `GameSyncFailure`

| Column | Type | Purpose |
|---|---|---|
| `id` | Integer PK | — |
| `game_id` | FK → Game | The incomplete game |
| `season_id` | Integer | For easy admin filtering |
| `abandoned_at` | DateTime | When we gave up |
| `missing_fields` | JSON | Fields that were still missing at abandon time |
| `can_retry` | Boolean | Admin flips to `True` to queue a manual retry |
| `retried_at` | DateTime | Null until a retry is attempted |

### Startup migration

Run idempotently on every app start (existing pattern):
- Finished games that already have events + lineup → `complete`
- Finished games missing data → `post_game` (with `give_up_at = now + 3 days`)
- All other games → `upcoming`

---

## Completeness Check

### `TIER_COMPLETENESS_FIELDS` config

Lives in a dedicated config module (e.g. `services/game_completeness.py`). Updated empirically as each league's API coverage is confirmed by testing — no logic changes required, only config updates.

```python
TIER_COMPLETENESS_FIELDS: dict[int, set[str]] = {
    1: {"score", "referees", "spectators", "events", "lineup", "best_players"},
    2: {"score", "referees", "spectators", "events", "lineup", "best_players"},
    3: {"score"},  # to be confirmed
    4: {"score"},  # to be confirmed
    5: {"score"},  # to be confirmed
    6: {"score"},  # to be confirmed
}
```

### `_is_game_complete(game, tier, session) → tuple[bool, list[str]]`

Returns `(is_complete, missing_fields)`.

| Field key | Check |
|---|---|
| `score` | `home_score` and `away_score` are not null |
| `referees` | `referee_1` is not null |
| `spectators` | `spectators` is not null |
| `events` | at least 1 `GameEvent` row exists for this game |
| `lineup` | at least 1 `GamePlayer` row exists for this game |
| `best_players` | exactly 2 best-player records exist for this game (one per team) |

Only fields listed in `TIER_COMPLETENESS_FIELDS[tier]` are checked. Unknown tiers fall back to `{"score"}`.

---

## Scheduler Jobs

### Job 1: `upcoming_games`

| Property | Value |
|---|---|
| Triggers | 12:00, 18:00, 23:00 UTC daily |
| Target | Games where `completeness_status = 'upcoming'` |
| Fetches | Game metadata: date, time, teams, venue, pre-assigned referees |
| Transition | If API returns `status = "finished"` → flip to `post_game`, set `give_up_at = game_date + 3 days` |

Covers schedule corrections (time changes, referee pre-assignments, venue changes) across the three typical Swiss game windows.

### Job 2: `post_game_completion`

| Property | Value |
|---|---|
| Triggers | Every 2 hours |
| Target | Games where `completeness_status = 'post_game'` |
| Fetches | Tier-aware: events, lineup, score details, referees, spectators, best players |
| On complete | Flip to `complete`, clear `incomplete_fields`, set `completeness_checked_at` |
| On incomplete, within deadline | Update `incomplete_fields`, retry next tick |
| On incomplete, past `give_up_at` | Flip to `abandoned`, write `GameSyncFailure` row |

### Manual retry (admin)

Admin sets `GameSyncFailure.can_retry = True` via admin panel. On next scheduler tick, the job:
1. Detects `can_retry = True` rows
2. Resets the game to `post_game` with `give_up_at = now + 3 days`
3. Sets `retried_at` on the failure row

---

## What Gets Removed

- `_game_events_ttl_hours()` — age-based TTL function (replaced by lifecycle state)
- Scheduler policies: `games`, `game_lineups`, `game_events` — replaced by the two new jobs above

---

## Testing Strategy

1. **Unit tests for `_is_game_complete`**: cover each field check, each tier, missing fields return correctly.
2. **Unit tests for state transitions**: upcoming → post_game on finish, post_game → complete, post_game → abandoned past deadline.
3. **Integration test for manual retry**: set `can_retry = True`, assert game resets to `post_game`.
4. **Migration test**: seed DB with finished games in various states, assert migration assigns correct `completeness_status`.
5. **Empirical tier mapping**: run `post_game_completion` job against each real league and observe which fields populate — update `TIER_COMPLETENESS_FIELDS` accordingly.
