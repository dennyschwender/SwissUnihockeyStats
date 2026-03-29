# Player Detail Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich the player detail page with cached biographical data (photo, height, weight, position, license), add PPG as a derived stat, and improve recent games with "show more" pagination.

**Architecture:** Two phases — Phase 1 adds new `Player` DB columns with an end-of-August TTL cache populated on page view; Phase 2 adds PPG to stats, a new `/api/v1/players/{id}/games` endpoint for HTMX pagination, and updates the template.

**Tech Stack:** SQLAlchemy (SQLite), FastAPI, Jinja2, HTMX, pytest

---

## File Map

| File | Change |
|---|---|
| `backend/app/models/db_models.py` | Add 6 columns to `Player` |
| `backend/app/services/database.py` | Add idempotent migration for new columns |
| `backend/app/lib/player_translations.py` | NEW — position/license translation lookup |
| `backend/app/services/stats_service.py` | TTL helper, populate new fields, PPG, pagination |
| `backend/app/api/v1/endpoints/players.py` | Add `GET /{player_id}/games` endpoint |
| `backend/templates/player_detail.html` | Bio row, PPG badge, PPG column, show-more |
| `backend/locales/{de,en,fr,it}/messages.json` | Add `player.height`, `player.weight`, `player.ppg` keys |
| `backend/tests/test_player_detail_enrichment.py` | NEW — tests for TTL helper, translations, PPG |

---

## Task 1: Add new columns to `Player` model

**Files:**
- Modify: `backend/app/models/db_models.py` (class Player, ~line 172)

- [ ] **Step 1: Add columns to the Player class**

In `db_models.py`, add the following 6 mapped columns to the `Player` class, after the `api_skip_until` line (~line 190):

```python
    photo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    height_cm: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    weight_kg: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    position_raw: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    license_raw: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    player_details_fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/models/db_models.py
git commit -m "feat: add biographical cache columns to Player model"
```

---

## Task 2: Add idempotent DB migration for new columns

**Files:**
- Modify: `backend/app/services/database.py` (`_run_sqlite_migrations`, ~line 210)

- [ ] **Step 1: Write a failing test**

Create `backend/tests/test_player_detail_enrichment.py`:

```python
"""Tests for player detail enrichment: TTL helper, translations, PPG."""
import pytest
from datetime import datetime, timezone


def test_migration_adds_player_columns(client):
    """New Player columns exist in the DB after initialization."""
    from app.services.database import get_database_service
    from sqlalchemy import text

    db = get_database_service()
    with db.engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(players)"))}
    assert "photo_url" in cols
    assert "height_cm" in cols
    assert "weight_kg" in cols
    assert "position_raw" in cols
    assert "license_raw" in cols
    assert "player_details_fetched_at" in cols
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && .venv/bin/pytest tests/test_player_detail_enrichment.py::test_migration_adds_player_columns -v
```
Expected: FAIL — columns not yet in migration.

- [ ] **Step 3: Add the migration stanza**

In `_run_sqlite_migrations`, add a new block after the existing `player_statistics` migration block:

```python
            # ── Add biographical cache columns to players ────────────────────
            existing_player_cols = {
                row[1] for row in conn.execute(text("PRAGMA table_info(players)"))
            }
            for col, typedef in [
                ("photo_url", "VARCHAR(500)"),
                ("height_cm", "INTEGER"),
                ("weight_kg", "INTEGER"),
                ("position_raw", "VARCHAR(50)"),
                ("license_raw", "VARCHAR(100)"),
                ("player_details_fetched_at", "DATETIME"),
            ]:
                if col not in existing_player_cols:
                    conn.execute(text(f"ALTER TABLE players ADD COLUMN {col} {typedef}"))
```

Place this block inside the `with self.engine.connect() as conn:` block, before the `conn.commit()` at the end of the existing migrations.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && .venv/bin/pytest tests/test_player_detail_enrichment.py::test_migration_adds_player_columns -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/database.py backend/tests/test_player_detail_enrichment.py
git commit -m "feat: migrate Player table with biographical cache columns"
```

---

## Task 3: Create player_translations module

**Files:**
- Create: `backend/app/lib/player_translations.py`

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/test_player_detail_enrichment.py`:

```python
def test_translate_position_known_locale():
    from app.lib.player_translations import translate_position
    assert translate_position("Stürmer", "en") == "Forward"
    assert translate_position("Verteidiger", "en") == "Defender"
    assert translate_position("Torhüter", "en") == "Goalkeeper"


def test_translate_position_de_returns_german():
    from app.lib.player_translations import translate_position
    assert translate_position("Stürmer", "de") == "Stürmer"


def test_translate_position_unknown_falls_back_to_raw():
    from app.lib.player_translations import translate_position
    assert translate_position("Libero", "en") == "Libero"


def test_translate_position_none_returns_none():
    from app.lib.player_translations import translate_position
    assert translate_position(None, "en") is None


def test_translate_license_known():
    from app.lib.player_translations import translate_license
    assert translate_license("Herren Aktive GF L-UPL", "en") == "Men Active GF L-UPL"
    assert translate_license("Damen Aktive GF L-UPL", "en") == "Women Active GF L-UPL"


def test_translate_license_unknown_falls_back():
    from app.lib.player_translations import translate_license
    assert translate_license("Junioren U21 A", "en") == "Junioren U21 A"


def test_translate_license_none_returns_none():
    from app.lib.player_translations import translate_license
    assert translate_license(None, "en") is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && .venv/bin/pytest tests/test_player_detail_enrichment.py -k "translate" -v
```
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Create the module**

Create `backend/app/lib/player_translations.py`:

```python
"""
Translations for player biographical fields sourced from the SwissUnihockey API.

The API returns German strings for position and license type.
These mappings translate known values to the app's four supported locales.
Unknown strings fall back to the raw API value.
"""
from typing import Optional

# Position strings as returned by the API (German)
_POSITION_MAP: dict[str, dict[str, str]] = {
    "Stürmer": {
        "de": "Stürmer",
        "en": "Forward",
        "fr": "Attaquant",
        "it": "Attaccante",
    },
    "Verteidiger": {
        "de": "Verteidiger",
        "en": "Defender",
        "fr": "Défenseur",
        "it": "Difensore",
    },
    "Torhüter": {
        "de": "Torhüter",
        "en": "Goalkeeper",
        "fr": "Gardien",
        "it": "Portiere",
    },
}

# License prefix replacements (order matters — longest first)
# Each tuple: (German prefix, locale → replacement)
_LICENSE_PREFIX_MAP: list[tuple[str, dict[str, str]]] = [
    (
        "Herren Aktive",
        {"de": "Herren Aktive", "en": "Men Active", "fr": "Hommes Actifs", "it": "Uomini Attivi"},
    ),
    (
        "Damen Aktive",
        {"de": "Damen Aktive", "en": "Women Active", "fr": "Femmes Actives", "it": "Donne Attive"},
    ),
]


def translate_position(raw: Optional[str], locale: str) -> Optional[str]:
    """Translate a raw API position string to the given locale.

    Returns the raw string if no mapping exists. Returns None if raw is None.
    """
    if raw is None:
        return None
    entry = _POSITION_MAP.get(raw)
    if entry is None:
        return raw
    return entry.get(locale, raw)


def translate_license(raw: Optional[str], locale: str) -> Optional[str]:
    """Translate a raw API license string to the given locale.

    Only the known prefix is translated; the remainder of the string is kept as-is.
    Returns the raw string if no prefix matches. Returns None if raw is None.
    """
    if raw is None:
        return None
    for german_prefix, translations in _LICENSE_PREFIX_MAP:
        if raw.startswith(german_prefix):
            translated_prefix = translations.get(locale, german_prefix)
            suffix = raw[len(german_prefix):]
            return translated_prefix + suffix
    return raw
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && .venv/bin/pytest tests/test_player_detail_enrichment.py -k "translate" -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/lib/player_translations.py backend/tests/test_player_detail_enrichment.py
git commit -m "feat: add player position/license translation module"
```

---

## Task 4: TTL helper + populate biographical fields in stats_service

**Files:**
- Modify: `backend/app/services/stats_service.py`

The API cells structure for `get_player_details(person_id)`:
- `cells[0]` → `image.url` (photo)
- `cells[1]` → club name (ignored here)
- `cells[2]` → jersey number (ignored — already on TeamPlayer)
- `cells[3]` → position string e.g. "Stürmer"
- `cells[4]` → year of birth e.g. "2003"
- `cells[5]` → height e.g. "179 cm"
- `cells[6]` → weight e.g. "70 kg"
- `cells[7]` → license e.g. "Herren Aktive GF L-UPL"

- [ ] **Step 1: Write failing tests for the TTL helper**

Add to `backend/tests/test_player_detail_enrichment.py`:

```python
def test_player_details_stale_when_none():
    from app.services.stats_service import _player_details_stale
    assert _player_details_stale(None) is True


def test_player_details_stale_before_aug31_this_year():
    """Fetched before the most recent Aug 31 → stale."""
    from app.services.stats_service import _player_details_stale
    # Simulate "today is 2026-03-29", fetched in 2025 before Aug 31
    fetched = datetime(2025, 7, 1, tzinfo=timezone.utc)
    assert _player_details_stale(fetched, _today=datetime(2026, 3, 29, tzinfo=timezone.utc)) is True


def test_player_details_fresh_after_aug31():
    """Fetched after the most recent Aug 31 → not stale."""
    from app.services.stats_service import _player_details_stale
    fetched = datetime(2025, 9, 5, tzinfo=timezone.utc)
    assert _player_details_stale(fetched, _today=datetime(2026, 3, 29, tzinfo=timezone.utc)) is False


def test_player_details_stale_before_aug31_same_year():
    """Today is Sept 15; fetched Aug 1 of same year → stale."""
    from app.services.stats_service import _player_details_stale
    fetched = datetime(2025, 8, 1, tzinfo=timezone.utc)
    assert _player_details_stale(fetched, _today=datetime(2025, 9, 15, tzinfo=timezone.utc)) is True


def test_player_details_fresh_when_fetched_same_day_as_aug31():
    """Fetched exactly on Aug 31 → not stale."""
    from app.services.stats_service import _player_details_stale
    fetched = datetime(2025, 8, 31, 12, 0, tzinfo=timezone.utc)
    assert _player_details_stale(fetched, _today=datetime(2026, 3, 1, tzinfo=timezone.utc)) is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && .venv/bin/pytest tests/test_player_detail_enrichment.py -k "stale" -v
```
Expected: FAIL — function doesn't exist.

- [ ] **Step 3: Add the TTL helper to stats_service.py**

Add this function near the top of `stats_service.py`, before `get_player_detail` (around line 1882):

```python
def _player_details_stale(
    fetched_at: Optional[datetime],
    _today: Optional[datetime] = None,
) -> bool:
    """Return True if player biographical details need refreshing.

    Data is considered fresh if it was fetched after the most recent August 31st.
    This aligns with the new season registration cycle (September).

    Args:
        fetched_at: The datetime when details were last fetched. None → always stale.
        _today: Override today's date (for testing). Defaults to UTC now.
    """
    if fetched_at is None:
        return True
    today = _today or datetime.now(timezone.utc)
    # Find the most recent Aug 31 (this year if we're past it, else last year)
    aug31_this_year = today.replace(month=8, day=31, hour=0, minute=0, second=0, microsecond=0)
    cutoff = aug31_this_year if today >= aug31_this_year else aug31_this_year.replace(year=today.year - 1)
    # Normalise fetched_at to UTC-aware for comparison
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    return fetched_at < cutoff
```

- [ ] **Step 4: Run TTL tests to verify they pass**

```bash
cd backend && .venv/bin/pytest tests/test_player_detail_enrichment.py -k "stale" -v
```
Expected: all PASS

- [ ] **Step 5: Update get_player_detail to populate new fields**

In `get_player_detail`, replace the existing API call block (currently ~lines 2133–2163) with:

```python
    # Fetch/refresh biographical data if stale (TTL: end of August each year)
    try:
        from app.services.swissunihockey import get_swissunihockey_client
        from app.lib.player_translations import translate_position, translate_license

        if _player_details_stale(result.get("player_details_fetched_at")):
            client = get_swissunihockey_client()
            api_data = client.get_player_details(person_id)
            regions = api_data.get("data", {}).get("regions", [])
            if regions:
                cells = regions[0].get("rows", [{}])[0].get("cells", [])
                if cells:
                    def _cell_text(idx):
                        if idx >= len(cells):
                            return None
                        cell = cells[idx]
                        texts = cell.get("text", []) if isinstance(cell, dict) else []
                        if isinstance(texts, list):
                            return str(texts[0]).strip() if texts else None
                        return str(texts).strip() or None

                    photo_url = None
                    img = cells[0].get("image", {}) if isinstance(cells[0], dict) else {}
                    photo_url = img.get("url") or None

                    position_raw = _cell_text(3)
                    year_of_birth_str = _cell_text(4)
                    height_str = _cell_text(5)   # e.g. "179 cm"
                    weight_str = _cell_text(6)   # e.g. "70 kg"
                    license_raw = _cell_text(7)

                    def _parse_int_prefix(s):
                        """Parse leading integer from strings like '179 cm' → 179."""
                        if not s:
                            return None
                        try:
                            return int(s.split()[0])
                        except (ValueError, IndexError):
                            return None

                    height_cm = _parse_int_prefix(height_str)
                    weight_kg = _parse_int_prefix(weight_str)

                    # Backfill year_of_birth if missing
                    if not result["year_of_birth"] and year_of_birth_str:
                        try:
                            yob = int(year_of_birth_str)
                            if 1950 <= yob <= 2025:
                                result["year_of_birth"] = yob
                        except (ValueError, TypeError):
                            pass

                    result["photo_url"] = photo_url
                    result["height_cm"] = height_cm
                    result["weight_kg"] = weight_kg
                    result["position_raw"] = position_raw
                    result["license_raw"] = license_raw

                    # Persist to DB
                    db = get_database_service()
                    with db.session_scope() as session:
                        player_row = session.query(Player).filter(
                            Player.person_id == person_id
                        ).first()
                        if player_row:
                            player_row.photo_url = photo_url
                            player_row.height_cm = height_cm
                            player_row.weight_kg = weight_kg
                            player_row.position_raw = position_raw
                            player_row.license_raw = license_raw
                            player_row.player_details_fetched_at = datetime.now(timezone.utc)
                            if not player_row.year_of_birth and result["year_of_birth"]:
                                player_row.year_of_birth = result["year_of_birth"]
        else:
            # Use cached values already loaded from DB into result
            pass

        # Apply translations using the request locale
        result["position"] = translate_position(result.get("position_raw"), locale)
        result["license"] = translate_license(result.get("license_raw"), locale)

    except Exception:
        pass
```

Also update the `result` dict built from the DB (around line 2121) to include the new fields from DB cache:

```python
        result = {
            "person_id": player.person_id,
            "name": player.full_name or f"Player {player.person_id}",
            "first_name": player.first_name or "",
            "last_name": player.last_name or "",
            "year_of_birth": player.year_of_birth,
            "career": career,
            "totals": totals,
            "recent_games": recent_games,
            # Biographical cache fields
            "photo_url": player.photo_url,
            "height_cm": player.height_cm,
            "weight_kg": player.weight_kg,
            "position_raw": player.position_raw,
            "license_raw": player.license_raw,
            "player_details_fetched_at": player.player_details_fetched_at,
            # Translated fields — populated after API check below
            "position": None,
            "license": None,
        }
```

Also update the `get_player_detail` function signature to accept a `locale` parameter:

```python
def get_player_detail(person_id: int, locale: str = "de") -> dict:
```

- [ ] **Step 6: Update the caller in main.py to pass locale**

Find the `get_player_detail` call in `main.py` and update it:

```python
player = get_player_detail(person_id, locale=locale)
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/stats_service.py backend/app/main.py backend/tests/test_player_detail_enrichment.py
git commit -m "feat: cache player biographical data with end-of-August TTL"
```

---

## Task 5: Add PPG to stats

**Files:**
- Modify: `backend/app/services/stats_service.py`

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/test_player_detail_enrichment.py`:

```python
def test_ppg_calculated_per_career_row():
    """PPG = points / games_played, rounded to 2dp."""
    from app.services.stats_service import _compute_ppg
    assert _compute_ppg(points=30, games_played=20) == 1.50
    assert _compute_ppg(points=7, games_played=3) == 2.33


def test_ppg_none_when_no_games():
    from app.services.stats_service import _compute_ppg
    assert _compute_ppg(points=0, games_played=0) is None
    assert _compute_ppg(points=5, games_played=0) is None


def test_ppg_none_when_games_none():
    from app.services.stats_service import _compute_ppg
    assert _compute_ppg(points=5, games_played=None) is None
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && .venv/bin/pytest tests/test_player_detail_enrichment.py -k "ppg" -v
```
Expected: FAIL

- [ ] **Step 3: Add _compute_ppg helper to stats_service.py**

Add near `_player_details_stale` (around line 1882):

```python
def _compute_ppg(points: Optional[int], games_played: Optional[int]) -> Optional[float]:
    """Compute points-per-game rounded to 2 decimal places. Returns None if no games."""
    if not games_played:
        return None
    return round((points or 0) / games_played, 2)
```

- [ ] **Step 4: Apply PPG to career rows and totals**

In `get_player_detail`, find where each `career` row dict is built (around line 2000–2030). Add `ppg` to each row:

```python
            career.append({
                ...existing fields...,
                "ppg": _compute_ppg(ps.points, ps.games_played),
            })
```

And in the `totals` dict (find where totals are computed):

```python
        totals = {
            ...existing fields...,
            "ppg": _compute_ppg(totals_points, totals_gp),
        }
```

Where `totals_points` and `totals_gp` are the summed values already computed. Check the exact variable names in the existing totals block — they will be something like `sum(...)` expressions assigned to local variables.

- [ ] **Step 5: Run PPG tests to verify they pass**

```bash
cd backend && .venv/bin/pytest tests/test_player_detail_enrichment.py -k "ppg" -v
```
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/stats_service.py backend/tests/test_player_detail_enrichment.py
git commit -m "feat: add PPG (points-per-game) to player career stats"
```

---

## Task 6: Recent games pagination

**Files:**
- Modify: `backend/app/services/stats_service.py`
- Modify: `backend/app/api/v1/endpoints/players.py`

- [ ] **Step 1: Write failing test for the new function**

Add to `backend/tests/test_player_detail_enrichment.py`:

```python
def test_get_player_recent_games_returns_limited_rows(client):
    """get_player_recent_games respects limit and returns has_more flag."""
    from app.services.stats_service import get_player_recent_games
    # Person_id 0 has no games — should return empty list with has_more=False
    result = get_player_recent_games(person_id=0, offset=0, limit=10)
    assert "rows" in result
    assert "has_more" in result
    assert result["has_more"] is False
    assert isinstance(result["rows"], list)
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd backend && .venv/bin/pytest tests/test_player_detail_enrichment.py::test_get_player_recent_games_returns_limited_rows -v
```
Expected: FAIL

- [ ] **Step 3: Extract recent games logic into a standalone function**

In `stats_service.py`, add a new function `get_player_recent_games` that reuses the existing query logic from `get_player_detail`. The function should:

1. Accept `person_id: int`, `offset: int = 0`, `limit: int = 10`
2. Run the same recent-games query that currently lives in `get_player_detail`
3. Return `{"rows": [...], "has_more": bool}`

The `has_more` flag is determined by querying for `limit + 1` rows and checking if more than `limit` were returned (then truncate to `limit`).

```python
def get_player_recent_games(
    person_id: int, offset: int = 0, limit: int = 10
) -> dict:
    """Return a page of recent game appearances for a player.

    Args:
        person_id: The player's person_id.
        offset: Number of rows to skip.
        limit: Number of rows to return.

    Returns:
        {"rows": [list of game dicts], "has_more": bool}
    """
    db = get_database_service()
    with db.session_scope() as session:
        # Fetch limit+1 to detect if more rows exist
        rows = _fetch_recent_game_rows(session, person_id, offset=offset, limit=limit + 1)
    has_more = len(rows) > limit
    return {"rows": rows[:limit], "has_more": has_more}
```

Extract the current recent-games query inside `get_player_detail` into a private helper `_fetch_recent_game_rows(session, person_id, offset, limit)`. Then call this helper from both `get_player_detail` (with `offset=0, limit=11` to get first 10 + has_more) and `get_player_recent_games`.

Update `get_player_detail` to use the first 10 rows and include `has_more`:

```python
        recent_result = _fetch_recent_game_rows(session, person_id, offset=0, limit=11)
        recent_games = recent_result[:10]
        recent_has_more = len(recent_result) > 10
```

And add `"recent_has_more": recent_has_more` to the result dict.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && .venv/bin/pytest tests/test_player_detail_enrichment.py::test_get_player_recent_games_returns_limited_rows -v
```
Expected: PASS

- [ ] **Step 5: Add the API endpoint**

In `backend/app/api/v1/endpoints/players.py`, add:

```python
from app.services.stats_service import get_player_recent_games as _get_recent_games

@router.get("/{player_id}/games")
async def get_player_games(
    player_id: int,
    offset: int = Query(0, ge=0, description="Number of rows to skip"),
    limit: int = Query(10, ge=1, le=50, description="Rows per page"),
):
    """Return a page of recent game appearances for a player (for HTMX pagination)."""
    import asyncio
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None, lambda: _get_recent_games(player_id, offset=offset, limit=limit)
        )
        return result
    except Exception as e:
        logger.error("Error fetching games for player %s: %s", player_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/stats_service.py backend/app/api/v1/endpoints/players.py backend/tests/test_player_detail_enrichment.py
git commit -m "feat: add recent games pagination for player detail"
```

---

## Task 7: Add i18n keys

**Files:**
- Modify: `backend/locales/de/messages.json`
- Modify: `backend/locales/en/messages.json`
- Modify: `backend/locales/fr/messages.json`
- Modify: `backend/locales/it/messages.json`

- [ ] **Step 1: Add keys to all four locale files**

In each file, find the `"player"` section and add the following keys:

**de:**
```json
"height": "Grösse",
"weight": "Gewicht",
"ppg": "P/Sp",
"show_more_games": "Mehr laden"
```

**en:**
```json
"height": "Height",
"weight": "Weight",
"ppg": "PPG",
"show_more_games": "Load more"
```

**fr:**
```json
"height": "Taille",
"weight": "Poids",
"ppg": "Pts/J",
"show_more_games": "Charger plus"
```

**it:**
```json
"height": "Altezza",
"weight": "Peso",
"ppg": "Pts/P",
"show_more_games": "Carica altro"
```

- [ ] **Step 2: Commit**

```bash
git add backend/locales/
git commit -m "i18n: add player height/weight/ppg/show_more translation keys"
```

---

## Task 8: Update player_detail.html template

**Files:**
- Modify: `backend/templates/player_detail.html`

- [ ] **Step 1: Add bio info row under the player name**

Replace the current header body block (lines 13–19):

```html
    <div class="detail-header-body">
      <a href="javascript:history.back()" class="back-link">← {{ t.common.back }}</a>
      <h1 class="detail-title" style="margin:.5rem 0 0;">{{ player.name if player else "Player" }}</h1>
      {% if player and player.year_of_birth %}
      <p class="detail-meta" style="margin:.25rem 0 0;">{{ t.player.born }} {{ player.year_of_birth }}</p>
      {% endif %}
    </div>
```

With:

```html
    <div class="detail-header-body">
      <a href="javascript:history.back()" class="back-link">← {{ t.common.back }}</a>
      <h1 class="detail-title" style="margin:.5rem 0 0;">{{ player.name if player else "Player" }}</h1>
      {% if player %}
      {% set bio_parts = [] %}
      {% if player.position %}{% set _ = bio_parts.append(player.position) %}{% endif %}
      {% if player.height_cm %}{% set _ = bio_parts.append(player.height_cm ~ " cm") %}{% endif %}
      {% if player.weight_kg %}{% set _ = bio_parts.append(player.weight_kg ~ " kg") %}{% endif %}
      {% if player.license %}{% set _ = bio_parts.append(player.license) %}{% endif %}
      {% if player.year_of_birth %}{% set _ = bio_parts.append(t.player.born ~ " " ~ player.year_of_birth) %}{% endif %}
      {% if bio_parts %}
      <p class="detail-meta" style="margin:.25rem 0 0;font-size:.85rem;color:var(--gray-500);">
        {{ bio_parts | join(' · ') }}
      </p>
      {% endif %}
      {% endif %}
    </div>
```

- [ ] **Step 2: Add PPG to header stat badges**

Find the `stats` variable in the header badges block (around line 32) and add PPG:

```html
    {% set stats = [
      ('GP',              player.totals.gp),
      ('G',               player.totals.g),
      ('A',               player.totals.a),
      ('PTS',             player.totals.pts),
      ('PIM',             player.totals.pim),
      (t.player.ppg,      player.totals.ppg),
    ] %}
```

- [ ] **Step 3: Add PPG column to career table**

In the `<thead>` row, add after the PTS column:

```html
            <th class="col-narrow">{{ t.player.ppg }}</th>
```

In the `<tbody>` rows, add after the PTS cell:

```html
            <td class="col-narrow" style="color:var(--gray-500);">{{ row.ppg if row.ppg is not none else '–' }}</td>
```

In the totals row, add after the PTS cell:

```html
            <td class="col-narrow" style="color:var(--gray-500);">{{ player.totals.ppg if player.totals.ppg is not none else '–' }}</td>
```

- [ ] **Step 4: Replace recent games section with paginated version**

Replace the current recent games section (lines 112–168) with:

```html
  <!-- Recent Game Appearances -->
  {% if player.recent_games %}
  <div class="section-block">
    <h2 class="section-block-title" style="margin-bottom:.75rem;">Recent Games</h2>
    <div class="table-scroll">
      <table class="data-table" style="width:100%;border-collapse:collapse;font-size:.875rem;">
        <thead>
          <tr>
            <th>Date</th>
            <th class="col-narrow" style="font-size:.75rem;color:var(--gray-500);">League</th>
            <th class="col-narrow" style="font-size:.75rem;color:var(--gray-500);">H/A</th>
            <th>Opponent</th>
            <th class="col-narrow" style="font-weight:700;">Result</th>
            <th class="col-narrow">G</th>
            <th class="col-narrow">A</th>
            <th class="col-narrow">Pts</th>
            <th class="col-narrow">PIM</th>
          </tr>
        </thead>
        <tbody id="recent-games-body">
          {% for g in player.recent_games %}
          {% include "partials/player_game_row.html" %}
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% if player.recent_has_more %}
    <div id="show-more-container" style="text-align:center;margin-top:.75rem;">
      <button
        hx-get="/api/v1/players/{{ player.person_id }}/games?offset=10&limit=10"
        hx-target="#recent-games-body"
        hx-swap="beforeend"
        hx-on::after-request="
          const btn = document.getElementById('show-more-btn');
          const resp = event.detail.xhr.response;
          try {
            const data = JSON.parse(resp);
            if (!data.has_more) btn.parentElement.remove();
            else {
              const url = new URL(btn.getAttribute('hx-get'), window.location.origin);
              url.searchParams.set('offset', parseInt(url.searchParams.get('offset')) + 10);
              btn.setAttribute('hx-get', url.pathname + url.search);
              htmx.process(btn);
            }
          } catch(e) {}
        "
        id="show-more-btn"
        class="btn-secondary"
        style="padding:.5rem 1.5rem;font-size:.875rem;">
        {{ t.player.show_more_games }}
      </button>
    </div>
    {% endif %}
  </div>
  {% endif %}
```

- [ ] **Step 5: Create the partial template for game rows**

Create `backend/templates/partials/player_game_row.html`:

```html
<tr style="border-bottom:1px solid var(--gray-100);cursor:pointer;"
  onclick="window.location='/{{ locale }}/game/{{ g.game_id }}'"
  onmouseover="this.style.background='var(--gray-50)'" onmouseout="this.style.background=''">
  <td style="padding:.6rem .75rem;color:var(--gray-500);">{{ g.date }}</td>
  <td style="padding:.6rem .5rem;text-align:center;font-size:.75rem;color:var(--gray-500);">{{ g.league or '–' }}</td>
  <td style="padding:.6rem .35rem;text-align:center;font-size:.75rem;color:var(--gray-400);">{{ g.home_away }}</td>
  <td style="padding:.6rem .75rem;">
    <a href="/{{ locale }}/team/{{ g.opponent_id }}" onclick="event.stopPropagation()" style="color:inherit;text-decoration:none;">{{ g.opponent }}</a>
  </td>
  <td style="padding:.6rem .75rem;text-align:center;">
    {% if g.result == 'W' %}<span style="font-weight:700;color:#16a34a;">W {{ g.score }}</span>
    {% elif g.result == 'OTW' %}<span style="font-weight:700;color:#059669;">OTW {{ g.score }}</span>
    {% elif g.result == 'OTL' %}<span style="font-weight:700;color:#b45309;">OTL {{ g.score }}</span>
    {% elif g.result == 'L' %}<span style="font-weight:700;color:#dc2626;">L {{ g.score }}</span>
    {% elif g.result == 'D' %}<span style="font-weight:700;color:var(--gray-500);">D {{ g.score }}</span>
    {% else %}<span style="color:var(--gray-400);">–</span>{% endif %}
  </td>
  <td style="padding:.6rem .5rem;text-align:center;">{{ g.g if g.g is not none else '–' }}</td>
  <td style="padding:.6rem .5rem;text-align:center;">{{ g.a if g.a is not none else '–' }}</td>
  <td style="padding:.6rem .5rem;text-align:center;font-weight:{% if g.g or g.a %}600{% else %}400{% endif %};">{{ (g.g + g.a) if (g.g is not none and g.a is not none) else '–' }}</td>
  <td style="padding:.6rem .5rem;text-align:center;color:{% if g.pim %}#dc2626{% else %}inherit{% endif %};">{{ g.pim if g.pim is not none else '–' }}</td>
</tr>
```

Note: The HTMX `/{player_id}/games` endpoint must render this partial (not JSON row dicts) for `hx-swap="beforeend"` to work. Update the endpoint to return an `HTMLResponse` using this partial template, passing `locale` from a query param.

Update `GET /{player_id}/games` in `players.py` to accept `locale: str = Query("de")` and return rendered HTML rows:

```python
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request

templates = Jinja2Templates(directory="templates")

@router.get("/{player_id}/games", response_class=HTMLResponse)
async def get_player_games(
    request: Request,
    player_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=50),
    locale: str = Query("de"),
):
    import asyncio
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None, lambda: _get_recent_games(player_id, offset=offset, limit=limit)
        )
        rows = result["rows"]
        has_more = result["has_more"]
        return templates.TemplateResponse(
            "partials/player_games_fragment.html",
            {"request": request, "rows": rows, "has_more": has_more,
             "player_id": player_id, "locale": locale,
             "next_offset": offset + limit},
        )
    except Exception as e:
        logger.error("Error fetching games for player %s: %s", player_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
```

Create `backend/templates/partials/player_games_fragment.html`:

```html
{% for g in rows %}
{% include "partials/player_game_row.html" %}
{% endfor %}
{% if has_more %}
<tr id="show-more-row-{{ next_offset }}">
  <td colspan="9" style="text-align:center;padding:.75rem;">
    <button
      hx-get="/api/v1/players/{{ player_id }}/games?offset={{ next_offset }}&limit=10&locale={{ locale }}"
      hx-target="#show-more-row-{{ next_offset }}"
      hx-swap="outerHTML"
      class="btn-secondary"
      style="padding:.5rem 1.5rem;font-size:.875rem;">
      Load more
    </button>
  </td>
</tr>
{% endif %}
```

Update the initial "show more" button in `player_detail.html` to match this pattern — replace the JS-heavy version from Step 4 with an equivalent `<tr>` that the fragment replaces:

```html
    {% if player.recent_has_more %}
    <tbody id="show-more-anchor">
      <tr>
        <td colspan="9" style="text-align:center;padding:.75rem;">
          <button
            hx-get="/api/v1/players/{{ player.person_id }}/games?offset=10&limit=10&locale={{ locale }}"
            hx-target="closest tr"
            hx-swap="outerHTML"
            class="btn-secondary"
            style="padding:.5rem 1.5rem;font-size:.875rem;">
            {{ t.player.show_more_games }}
          </button>
        </td>
      </tr>
    </tbody>
    {% endif %}
```

Place this `<tbody>` after the first `</tbody>` closing tag of the recent games table.

- [ ] **Step 6: Run the full test suite**

```bash
cd backend && .venv/bin/pytest --tb=short -q
```
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/templates/ backend/locales/ backend/app/api/v1/endpoints/players.py
git commit -m "feat: update player detail template with bio row, PPG, show-more pagination"
```

---

## Task 9: Smoke test on production DB

- [ ] **Step 1: Start the dev server**

```bash
cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000
```

- [ ] **Step 2: Open Pablo Mariotti's player page**

Navigate to `http://localhost:8000/de/player/471982`

Expected:
- Bio row shows: `Stürmer · 179 cm · 70 kg · Herren Aktive GF L-UPL · Born 2003`
- Stat badges include PPG
- Career table has PPG column
- Recent games shows 10 rows with "Load more" button if player has >10 game appearances
- Clicking "Load more" appends the next 10 rows

- [ ] **Step 3: Check English locale**

Navigate to `http://localhost:8000/en/player/471982`

Expected: Bio row shows `Forward · 179 cm · 70 kg · Men Active GF L-UPL · Born 2003`

- [ ] **Step 4: Commit if any template fixes needed, then done**
