# Local PlayerStatistics Computation (T1–T3) — Design Spec

**Date:** 2026-03-16
**Status:** Approved

---

## Goal

For Swiss Unihockey tiers 1–3, replace per-player API calls for `PlayerStatistics` with SQL aggregation over locally-stored `GamePlayer` / `GameEvent` rows from games that have `completeness_status='complete'`. Tiers 4–6 are unchanged.

---

## Background

The existing `index_player_stats` job calls `/api/players/{id}/statistics` once per player. For T1 (~641 players), T2 (~3,067), and T3 (~7,403) this takes hours. Since the game lifecycle refactor now stores complete per-game data (lineup + events) for all three tiers, we can compute the same statistics locally — instantly, at any cadence.

---

## Stats Computed per Tier

| Stat | T1 / T2 | T3 |
|---|---|---|
| `games_played` | ✓ local | ✓ local |
| `goals` | ✓ local | ✓ local |
| `assists` | ✓ local | ✓ local |
| `total_pim` | ✓ local | ✓ local |
| `pen_2min` | ✓ local | — |
| `pen_5min` | ✓ local | — |
| `pen_10min` | ✓ local | — |
| `pen_match` | ✓ local | — |
| `plus_minus` | ✓ local | — |
| Keeper stats (ga, saves, …) | kept from prior API fetch | kept from prior API fetch |

Fields not computed locally are left untouched on the `PlayerStatistics` row (preserving any previously API-fetched value).

---

## Data Sources

- **`GamePlayer`** — one row per player per game, seeded from the lineup API. Fields: `player_id`, `team_id`, `game_id`, `goals`, `assists`, `pim`, `pen_2min`, `pen_5min`, `pen_10min`, `pen_match`, `plus_minus`.
- **`GameEvent`** — one row per game event (goal, penalty, etc.). Contains player name strings but **no `player_id`** (API limitation). Used only for backfilling missing `GamePlayer` rows.

Scope: only games with `completeness_status='complete'` for the current season.

---

## Name-Matching Backfill

When a `GameEvent` references a player name with no matching `GamePlayer` row in the same team+game:

1. **Exact match** on `first_name + last_name` (case-insensitive) within the same `team_id` + `game_id` → update the `GamePlayer` row to link the event.
2. **No match** → insert an `UnresolvedPlayerEvent` record for admin review.
3. **Admin panel** shows unresolved names; admin can manually link or dismiss.

Unresolved events are **excluded** from stat computation (conservative — no phantom stats).

---

## New Job: `compute_player_stats`

A new scheduler job replaces `index_player_stats` for T1–T3:

1. Finds all players with `GamePlayer` rows in `complete` T1–T3 games for the current season.
2. For each player: single `GROUP BY` query aggregating goals, assists, pim, pen breakdowns, plus_minus, games_played.
3. Upserts `PlayerStatistics` with computed values + sets `computed_from_local=True` + `local_computed_at=now()`.

The existing `index_player_stats` job (per-player API) continues to run for T4–T6 only.

**Schedule:** Every 6 hours (cadence TBD — may be triggered after `post_game_completion` completes).

---

## Schema Changes

### `PlayerStatistics` (modify)
- Add `computed_from_local` (Boolean, default False, not null)
- Add `local_computed_at` (DateTime, nullable)

### `UnresolvedPlayerEvent` (new table)
- `id` — Integer PK
- `game_id` — Integer FK → Game.id
- `team_id` — Integer FK → Team.id
- `raw_name` — String (full name from event)
- `event_type` — String (goal / penalty / etc.)
- `created_at` — DateTime (default utcnow)
- `resolved_at` — DateTime nullable
- `resolved_by` — String nullable (admin action)

---

## Admin Panel

New section in the admin dashboard: **Unresolved Player Events**.

- Table: raw_name, event_type, game, team, created_at
- Per-row actions: **Link** (select player from team roster) or **Dismiss**
- Linked rows: update `GameEvent` + mark `resolved_at`; dismissed rows: set `resolved_at` with "dismissed" marker

---

## What Does NOT Change

- `index_player_game_stats` (fetches `GamePlayer` rows from API) — unchanged, still runs to seed the data this job reads from.
- `index_post_game_completion` — unchanged, marks games complete.
- T4–T6 `PlayerStatistics` — still API-fetched (no game data for those tiers).

---

## Out of Scope

- Real-time stat computation on game save
- Historical seasons (only current season in scope for now)
- Keeper-specific stats (ga, saves) — not available from GamePlayer rows; API-only

---

## Success Criteria

1. `PlayerStatistics` rows for T1–T3 players reflect accurate goals/assists/pim (and pen breakdown + plus_minus for T1/T2) within one job cycle.
2. `index_player_stats` API calls for T1–T3 players are eliminated.
3. Unresolved events are surfaced in admin panel, not silently dropped.
4. All existing tests pass; new tests cover aggregation logic and name-matching.
