# Player Detail Enrichment Design

**Date:** 2026-03-29
**Status:** Approved

## Overview

Enrich the player detail page with biographical data from the SwissUnihockey API (photo, height, weight, position, license), cache it in the DB with an end-of-August TTL, add PPG as a derived stat, and improve recent games with incremental "show more" pagination.

---

## Phase 1: Player model + TTL caching

### New DB columns on `Player`

| Column | Type | Notes |
|---|---|---|
| `photo_url` | `String`, nullable | Cloudinary URL from API |
| `height_cm` | `Integer`, nullable | Parsed from "179 cm" → 179 |
| `weight_kg` | `Integer`, nullable | Parsed from "70 kg" → 70 |
| `position_raw` | `String(50)`, nullable | Raw German string from API e.g. "Stürmer" |
| `license_raw` | `String(100)`, nullable | Raw German string from API e.g. "Herren Aktive GF L-UPL" |
| `player_details_fetched_at` | `DateTime`, nullable | TTL anchor for all 5 fields above |

All columns are additive (nullable, no default required). Added via SQLAlchemy's idempotent migration in `database.py`.

### TTL logic

A single helper function `_player_details_stale(fetched_at: datetime | None) -> bool`:
- Returns `True` if `fetched_at` is `None`
- Returns `True` if `fetched_at` is before the most recent August 31st (i.e. data is from the previous season)
- Returns `False` otherwise

This function is pure and trivially unit-testable.

**Rationale for end-of-August:** The new season registration opens in September. Photos, positions, and license types are updated at season start. Refreshing once per season (after Aug 31) ensures fresh data without hammering the API.

### Population in `get_player_detail`

In `stats_service.get_player_detail`:
1. After loading the `Player` row from DB, check `_player_details_stale(player.player_details_fetched_at)`
2. If stale: call `client.get_player_details(person_id)`, parse the cells array:
   - `cells[0].image.url` → `photo_url`
   - `cells[2].text[0]` → jersey number (ignored here, already on TeamPlayer)
   - `cells[3].text[0]` → `position_raw`
   - `cells[4].text[0]` → `year_of_birth` (existing fallback logic, unchanged)
   - `cells[5].text[0]` → `height_cm` (parse int from "179 cm")
   - `cells[6].text[0]` → `weight_kg` (parse int from "70 kg")
   - `cells[7].text[0]` → `license_raw`
   - Set `player_details_fetched_at = datetime.now(UTC)`
3. If API call fails: keep existing cached values, do not wipe. Log at DEBUG level.

The DB write happens inside the existing `session_scope` for the player row (not a separate session).

---

## Phase 2: Stats service + template

### Stats service changes

**`get_player_detail` return dict additions:**
- `photo_url`: from cached DB field (was previously fetched live on every call)
- `height_cm`: int or None
- `weight_kg`: int or None
- `position`: translated string (see Translation section below)
- `license`: translated string

**PPG (points-per-game):**
- Per career row: `ppg = round(points / games_played, 2) if games_played else None`
- In `totals`: same calculation over career totals
- Displayed as e.g. `1.23`, shown as `–` when None

**Recent games pagination:**
- `get_player_detail` returns only the first 10 recent games + `has_more: bool`
- New function `get_player_recent_games(person_id: int, offset: int, limit: int = 10) -> dict` returning `{"rows": [...], "has_more": bool}`

### New API endpoint

`GET /api/v1/players/{person_id}/games?offset=N`

- Returns JSON: `{"rows": [...], "has_more": bool}`
- Each row matches the existing recent_games dict structure
- Used by HTMX "show more" button

### Position/license translation

New lookup dict (in `app/lib/i18n.py` or a dedicated `app/lib/player_translations.py`):

```python
POSITION_TRANSLATIONS = {
    "Stürmer":    {"de": "Stürmer",    "en": "Forward",    "fr": "Attaquant",  "it": "Attaccante"},
    "Verteidiger":{"de": "Verteidiger","en": "Defender",   "fr": "Défenseur",  "it": "Difensore"},
    "Torhüter":   {"de": "Torhüter",  "en": "Goalkeeper", "fr": "Gardien",    "it": "Portiere"},
}
```

License translation maps known prefixes (e.g. "Herren Aktive" → "Men Active"). Unknown strings fall back to the raw value.

The `get_player_detail` function receives `locale: str` parameter (defaulting to `"de"`) and applies translations before returning.

### Template changes (`player_detail.html`)

**Header section** — new info row between name and stat badges:
```
Forward · 179 cm · 70 kg · Men Active NLA
```
Only non-None fields are shown. Fields separated by `·`. Hidden entirely if all fields are None.

**Stat badges** — add PPG badge:
```
GP  G   A   PTS  PIM  PPG
42  28  35  63   18   1.50
```

**Career table** — add PPG column after PTS:
```
Season  League  Team  GP  G   A   PTS  PPG   PIM
```

**Recent games** — show first 10 rows on load. Below the table:
```html
<button hx-get="/api/v1/players/{id}/games?offset=10"
        hx-target="#recent-games-body"
        hx-swap="beforeend"
        hx-include="[name='offset']">
  Show more
</button>
```
The button updates its own `offset` after each load and hides itself when `has_more` is false. HTMX renders a partial `<tr>` fragment + optionally a new button.

---

## Out of scope

- `plus_minus`: column exists in DB but is never populated (requires on-floor tracking not available). Not shown.
- Penalty breakdown (pen_2min/5min/10min/match): exists in DB but not surfaced in this iteration.
- Background scheduled refresh of player details (TTL refresh happens on page view only).
