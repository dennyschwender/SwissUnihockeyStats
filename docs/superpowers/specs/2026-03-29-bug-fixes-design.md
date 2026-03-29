# Bug Fixes Design — 2026-03-29

## Overview

Six bugs across locale persistence, player stats display, UI labels, league search, and load-more pagination.

---

## Bug 1 — Locale not persisted (root redirect always goes to DE)

**Problem:** `root_redirect` at `/` always redirects to `DEFAULT_LOCALE` ("de"). Navigating to `/` after using the site in English sends the user back to German.

**Fix:**
- Add a middleware (`LocaleCookieMiddleware`) that runs on every response for routes matching `/{locale}/...`. It reads the `locale` path param and sets a `preferred_locale` cookie (max_age=365 days, httponly=False so JS can read if needed).
- Update `root_redirect` to read `request.cookies.get("preferred_locale")`, validate it against `SUPPORTED_LOCALES`, and redirect there. Fall back to `DEFAULT_LOCALE` if absent or invalid.

**Files:** `backend/app/main.py` (middleware + `root_redirect`)

---

## Bug 2 — Player recent games showing 0 goals/assists

**Problem:** For player 471982 (and potentially others), the "Recent Games" table shows 0 goals and 0 assists even for games where the player scored.

**Root cause:** `GamePlayer` rows are inserted from lineup data with `goals=None`. `backfill_game_player_stats_from_events` then updates them from `GameEvent` rows by matching on `player_id`. If `GameEvent.player_id` is `None` for some events (name-to-ID resolution failed during indexing), those goals are never credited to the player.

**Investigation steps:**
1. Query DB for player 471982: check `GamePlayer.goals` vs `GameEvent` rows for the same games.
2. Check if `GameEvent.player_id` is `NULL` for the relevant events.
3. If so, the fix is in `backfill_game_player_stats_from_events` — improve name matching or trigger a re-backfill for affected players.

**Fix:** If the unresolved events have enough context (team_id + player name), improve the matching in `backfill_game_player_stats_from_events` to attempt a fuzzy name lookup against `Player` records for the same team. Add a re-index trigger for affected players.

**Files:** `backend/app/services/data_indexer.py` (`backfill_game_player_stats_from_events`)

---

## Bug 3 — H2H tab: rename "Recent Form"

**Problem:** The H2H tab in game detail shows "Recent Form" which is ambiguous — it's the form *before* the current game.

**Fix:** Update i18n key `game.recent_form` in all four locale files:
- `de`: `"Aktuelle Form (vor diesem Spiel)"`
- `en`: `"Recent Form (before this game)"`
- `fr`: `"Forme récente (avant ce match)"`
- `it`: `"Forma recente (prima di questa partita)"`

**Files:** `backend/locales/*/messages.json`

---

## Bug 4 — Game detail: rename "Playoff" tab to "Playoff/Playouts"

**Problem:** The playoff series tab is labelled "Playoff" but applies to both playoff and playout series.

**Fix:** Update i18n key `game.tab_playoff` in all four locale files:
- `de`: `"Playoff/Playouts"`
- `en`: `"Playoff/Playouts"`
- `fr`: `"Playoff/Playouts"`
- `it`: `"Playoff/Playouts"`

**Files:** `backend/locales/*/messages.json`

---

## Bug 5 — League scorer/penalty search doesn't find unloaded players

**Problem:** The search input in league detail (scorers and penalties tabs) only filters already-loaded rows client-side. Players not yet paginated in are invisible to search.

**Fix:**
- Add two new endpoints in `main.py`:
  - `GET /{locale}/league/{league_id}/scorers/search?q={query}` — queries `PlayerStatistics` joined with `Player` by name substring, returns HTML fragment of matching rows (same row structure as the scorers table).
  - `GET /{locale}/league/{league_id}/penalties/search?q={query}` — same for penalties (ordered by `pim` desc).
- Both endpoints return up to 50 results. Empty query returns the default top-N rows (same as initial page load).
- Update the search `<input>` in `league_detail.html` to use:
  - `hx-get="/{locale}/league/{league_id}/scorers/search"`
  - `hx-trigger="input delay:300ms"`
  - `hx-target="#scorers-tbody"` (or `#penalties-tbody`)
  - `hx-include="[name='q']"` (the input itself)
- Remove or disable the existing client-side JS filter when HTMX takes over.

**Files:** `backend/app/main.py`, `backend/templates/league_detail.html`

---

## Bug 6 — Player detail "Load More" returns 500

**Problem:** The HTMX "Load more" button on player detail pages hits `/api/v1/players/{id}/games?offset=10&limit=10&locale=en` and receives a 500.

**Likely causes:**
1. `_fetch_recent_game_rows` crashes when `g.game_date` is `None` (`.strftime()` on `None` raises `AttributeError`).
2. Other `None` fields accessed without guards (e.g., `g.period`, team name lookups).

**Fix:**
- In `_fetch_recent_game_rows`: guard `g.game_date` with `g.game_date.strftime(...) if g.game_date else ""` (likely already done for first load but verify offset > 0 path).
- Add proper exception logging in the API endpoint to surface the real error (currently catches all exceptions and returns 500 without detail in logs — verify `logger.error` is actually firing).
- Check if the issue is related to Bug 2 (None goals/assists) — the template handles those safely already.

**Files:** `backend/app/services/stats_service.py`, `backend/app/api/v1/endpoints/players.py`

---

## Out of Scope

- Enhancements (season history collapse, PPG in roster, timeline rework, referee/coach pages, standings grouping) — tracked in separate spec.
