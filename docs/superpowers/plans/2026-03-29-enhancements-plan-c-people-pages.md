# Enhancements Plan C — People Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add referee detail pages (query-based, no new model) and coach detail pages (new `Staff` DB model + API client method + indexer).

**Architecture:** Two independent sub-features. Referee pages are lightweight: `get_referee_games` queries the `Game` table by referee name, a new route serves the page, referee names in `game_detail.html` become links, and global search gains referee results. Coach pages are heavier: a new `Staff` ORM model, a new `get_team_staff` API client method, an indexer step, `get_coach_detail` service function, route, template, and integration into team/game detail pages and global search.

**Tech Stack:** Python/SQLAlchemy (`models`, `stats_service`, `data_indexer`, `api_client`, `main`), Jinja2 (templates), pytest

---

## File Map

| File | Change |
|---|---|
| `backend/app/models/db_models.py` | Add `Staff` model |
| `backend/app/services/api_client.py` | Add `get_team_staff(team_id)` method |
| `backend/app/services/data_indexer.py` | Add `index_team_staff(team_id, season_id)` + hook into team loop |
| `backend/app/services/stats_service.py` | Add `get_referee_games`, `get_coach_detail`; extend `get_team_detail` with `head_coach` |
| `backend/app/main.py` | Add `referee_detail`, `coach_detail` routes; extend global search |
| `backend/templates/referee_detail.html` | New page |
| `backend/templates/coach_detail.html` | New page |
| `backend/templates/game_detail.html` | Referee name → link; add coach names |
| `backend/templates/team_detail.html` | Add head coach line in header |
| `backend/locales/*/messages.json` | Add `referee` and `coach` i18n sections |
| `backend/tests/test_stats_service.py` | Tests for `get_referee_games`, `get_coach_detail` |
| `backend/tests/test_data_indexer.py` | Test for `index_team_staff` |

---

## Task 1: Add referee i18n keys

**Files:**
- Modify: `backend/locales/de/messages.json`, `en/`, `fr/`, `it/`

- [ ] **Step 1: Add referee and coach keys to all four locale files**

In each `messages.json`, add a top-level `"referee"` section and a `"coach"` section:

**`backend/locales/de/messages.json`** — add before the closing `}`:
```json
  "referee": {
    "page_title": "Schiedsrichter",
    "games_count": "Spiele als Schiedsrichter",
    "no_games": "Keine Spiele gefunden."
  },
  "coach": {
    "page_title": "Trainer",
    "head_coach": "Headcoach",
    "assistant_coach": "Assistenzcoach",
    "no_seasons": "Keine Saisons gefunden.",
    "season_history": "Stationsübersicht"
  }
```

**`backend/locales/en/messages.json`**:
```json
  "referee": {
    "page_title": "Referee",
    "games_count": "Games as referee",
    "no_games": "No games found."
  },
  "coach": {
    "page_title": "Coach",
    "head_coach": "Head Coach",
    "assistant_coach": "Assistant Coach",
    "no_seasons": "No seasons found.",
    "season_history": "Season History"
  }
```

**`backend/locales/fr/messages.json`**:
```json
  "referee": {
    "page_title": "Arbitre",
    "games_count": "Matchs en tant qu'arbitre",
    "no_games": "Aucun match trouvé."
  },
  "coach": {
    "page_title": "Entraîneur",
    "head_coach": "Entraîneur-chef",
    "assistant_coach": "Entraîneur-adjoint",
    "no_seasons": "Aucune saison trouvée.",
    "season_history": "Historique des saisons"
  }
```

**`backend/locales/it/messages.json`**:
```json
  "referee": {
    "page_title": "Arbitro",
    "games_count": "Partite come arbitro",
    "no_games": "Nessuna partita trovata."
  },
  "coach": {
    "page_title": "Allenatore",
    "head_coach": "Capo allenatore",
    "assistant_coach": "Assistente allenatore",
    "no_seasons": "Nessuna stagione trovata.",
    "season_history": "Storico stagioni"
  }
```

- [ ] **Step 2: Verify JSON is valid**

```bash
cd backend && python3 -c "
import json, os
for locale in ['de','en','fr','it']:
    path = f'locales/{locale}/messages.json'
    with open(path) as f:
        data = json.load(f)
    assert 'referee' in data, f'referee missing in {locale}'
    assert 'coach' in data, f'coach missing in {locale}'
print('All locale files valid')
"
```

Expected: `All locale files valid`

- [ ] **Step 3: Commit**

```bash
cd backend && git add locales/
git commit -m "i18n: add referee and coach translation keys"
```

---

## Task 2: Add get_referee_games to stats_service.py

**Files:**
- Modify: `backend/app/services/stats_service.py`
- Test: `backend/tests/test_stats_service.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_stats_service.py`:

```python
class TestGetRefereeGames:
    """Test get_referee_games returns correct structure."""

    def _seed_referee_games(self, session):
        from app.models.db_models import Game, Season
        session.merge(Season(id=2025, text="2024/25", highlighted=True))
        session.flush()
        session.add(Game(
            id=5001, season_id=2025,
            home_team_name="Team A", away_team_name="Team B",
            home_score=3, away_score=2,
            referee_1="John Referee",
            game_date=datetime(2025, 1, 15),
        ))
        session.add(Game(
            id=5002, season_id=2025,
            home_team_name="Team C", away_team_name="Team D",
            home_score=1, away_score=1,
            referee_2="John Referee",  # appears as referee_2
            game_date=datetime(2025, 2, 10),
        ))
        session.add(Game(
            id=5003, season_id=2025,
            home_team_name="Team E", away_team_name="Team F",
            home_score=None, away_score=None,
            referee_1="Other Referee",
            game_date=datetime(2025, 3, 1),
        ))

    def test_returns_games_for_referee(self):
        from app.services.stats_service import get_referee_games
        from app.services.database import get_database_service
        db = get_database_service()
        with db.session_scope() as session:
            self._seed_referee_games(session)
        with db.session_scope() as session:
            result = get_referee_games("John Referee", session)
        assert result["name"] == "John Referee"
        assert result["total"] == 2

    def test_matches_referee_1_and_referee_2(self):
        from app.services.stats_service import get_referee_games
        from app.services.database import get_database_service
        db = get_database_service()
        with db.session_scope() as session:
            result = get_referee_games("John Referee", session)
        game_ids = [g["game_id"] for g in result["games"]]
        assert 5001 in game_ids
        assert 5002 in game_ids
        assert 5003 not in game_ids

    def test_no_games_for_unknown_referee(self):
        from app.services.stats_service import get_referee_games
        from app.services.database import get_database_service
        db = get_database_service()
        with db.session_scope() as session:
            result = get_referee_games("Nobody Here", session)
        assert result["total"] == 0
        assert result["games"] == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && .venv/bin/pytest tests/test_stats_service.py::TestGetRefereeGames -v
```

Expected: FAIL — `ImportError: cannot import name 'get_referee_games'`.

- [ ] **Step 3: Add get_referee_games to stats_service.py**

Add after the global search helpers (around the end of the file, before the final closing):

```python
def get_referee_games(name: str, session) -> dict:
    """Return all games refereed by *name* (matches referee_1 or referee_2).

    Args:
        name: exact referee name string as stored in Game.referee_1 / referee_2.
        session: active SQLAlchemy session.
    """
    games = (
        session.query(Game)
        .filter(or_(Game.referee_1 == name, Game.referee_2 == name))
        .order_by(Game.game_date.desc())
        .all()
    )
    return {
        "name": name,
        "games": [
            {
                "game_id": g.id,
                "game_date": g.game_date.strftime("%d.%m.%Y") if g.game_date else "",
                "home_team": g.home_team_name or "",
                "away_team": g.away_team_name or "",
                "score": f"{g.home_score}:{g.away_score}" if g.home_score is not None else "",
                "league_name": g.league_name or "",
                "league_db_id": g.league_db_id,
                "season_id": g.season_id,
            }
            for g in games
        ],
        "total": len(games),
    }
```

Note: `or_` is already imported at the top of `stats_service.py`. `Game` is also already imported.

- [ ] **Step 4: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_stats_service.py::TestGetRefereeGames -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/services/stats_service.py tests/test_stats_service.py
git commit -m "feat: add get_referee_games to stats_service"
```

---

## Task 3: Referee detail route and template

**Files:**
- Modify: `backend/app/main.py`
- Create: `backend/templates/referee_detail.html`

- [ ] **Step 1: Add referee_detail route to main.py**

Add after the `coach_detail` or any nearby detail route (place after the `player_detail` route for consistency — find it around line 3907 area). Insert:

```python
@app.get("/{locale}/referee/{name:path}", response_class=HTMLResponse)
async def referee_detail(locale: str, name: str, request: Request):
    """Referee detail page — shows all games refereed by this person."""
    from urllib.parse import unquote
    from app.services.stats_service import get_referee_games
    from app.services.database import get_database_service
    t = get_translations(locale)
    db = get_database_service()
    decoded_name = unquote(name)
    with db.session_scope() as session:
        referee = get_referee_games(decoded_name, session)
    return templates.TemplateResponse(
        "referee_detail.html",
        {"request": request, "locale": locale, "t": t, "referee": referee},
    )
```

- [ ] **Step 2: Create referee_detail.html**

Create `backend/templates/referee_detail.html`:

```html
{% extends "base.html" %}
{% block title %}{{ t.referee.page_title }} — {{ referee.name }}{% endblock %}

{% block content %}
<div class="container page-content">
  <div style="margin-bottom:1.5rem;">
    <h1 style="font-size:1.75rem;font-weight:700;margin-bottom:.25rem;">🧑‍⚖️ {{ referee.name }}</h1>
    <p style="color:var(--gray-500);font-size:.9rem;">{{ t.referee.games_count }}: {{ referee.total }}</p>
  </div>

  {% if referee.games %}
  <div class="section-block">
    <div class="table-scroll">
      <table class="data-table">
        <thead>
          <tr>
            <th>{{ t.table.date }}</th>
            <th>{{ t.table.league }}</th>
            <th>{{ t.table.home_team }}</th>
            <th style="text-align:center;">Score</th>
            <th>{{ t.table.away_team }}</th>
          </tr>
        </thead>
        <tbody>
          {% for g in referee.games %}
          <tr class="clickable" onclick="window.location='/{{ locale }}/game/{{ g.game_id }}'">
            <td style="white-space:nowrap;color:var(--gray-500);">{{ g.game_date }}</td>
            <td style="font-size:.8rem;color:var(--gray-500);">
              {% if g.league_db_id %}<a href="/{{ locale }}/league/{{ g.league_db_id }}" class="link-inherit" onclick="event.stopPropagation()">{{ g.league_name }}</a>{% else %}{{ g.league_name }}{% endif %}
            </td>
            <td style="font-weight:500;">{{ g.home_team }}</td>
            <td style="text-align:center;font-weight:700;">
              {% if g.score %}{{ g.score }}{% else %}<span style="color:var(--gray-400);">vs</span>{% endif %}
            </td>
            <td style="font-weight:500;">{{ g.away_team }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
  {% else %}
  <div class="empty-state-center">
    <p class="empty-state-icon">🧑‍⚖️</p>
    <p>{{ t.referee.no_games }}</p>
  </div>
  {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 3: Run all tests**

```bash
cd backend && .venv/bin/pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
cd backend && git add app/main.py templates/referee_detail.html
git commit -m "feat: add referee detail page and route"
```

---

## Task 4: Referee links in game_detail.html + global search

**Files:**
- Modify: `backend/templates/game_detail.html`
- Modify: `backend/app/main.py` (global search endpoint)

- [ ] **Step 1: Make referee names clickable in game_detail.html**

Find the referee display line (~line 455):
```html
    {% if game.referee_1 or game.referee_2 %}
    <div class="gd-meta-venue" style="font-size:.75rem;color:var(--gray-500);">🧑‍⚖️ {{ game.referee_1 }}{% if game.referee_1 and game.referee_2 %} · {% endif %}{{ game.referee_2 }}</div>
```

Replace with:
```html
    {% if game.referee_1 or game.referee_2 %}
    <div class="gd-meta-venue" style="font-size:.75rem;color:var(--gray-500);">🧑‍⚖️
      {% if game.referee_1 %}<a href="/{{ locale }}/referee/{{ game.referee_1 | urlencode }}" style="color:inherit;text-decoration:none;" onmouseover="this.style.textDecoration='underline'" onmouseout="this.style.textDecoration='none'">{{ game.referee_1 }}</a>{% endif %}{% if game.referee_1 and game.referee_2 %} · {% endif %}{% if game.referee_2 %}<a href="/{{ locale }}/referee/{{ game.referee_2 | urlencode }}" style="color:inherit;text-decoration:none;" onmouseover="this.style.textDecoration='underline'" onmouseout="this.style.textDecoration='none'">{{ game.referee_2 }}</a>{% endif %}
    </div>
```

Note: Jinja2 has a built-in `urlencode` filter that percent-encodes strings.

- [ ] **Step 2: Add referee results to global search in main.py**

Find the `universal_search` endpoint (~line 4089). Inside the `with db.session_scope() as session:` block, after the Leagues section (after `html_parts.append("</div></div>")` for leagues), add:

```python
        # --- Referees ---
        from sqlalchemy import union
        ref1_q = (
            session.query(Game.referee_1.label("name"))
            .filter(Game.referee_1.ilike(f"%{q}%"), Game.referee_1.isnot(None))
        )
        ref2_q = (
            session.query(Game.referee_2.label("name"))
            .filter(Game.referee_2.ilike(f"%{q}%"), Game.referee_2.isnot(None))
        )
        referee_names = (
            session.query("name")
            .select_entity_from(union(ref1_q, ref2_q).alias("refs"))
            .limit(5)
            .all()
        )
        if referee_names:
            html_parts.append(
                '<div class="search-category"><h3>🧑‍⚖️ Referees</h3><div class="search-items">'
            )
            for (ref_name,) in referee_names:
                from urllib.parse import quote
                url = f"/{locale}/referee/{quote(ref_name)}"
                html_parts.append(
                    f'<div class="search-item" onclick="window.location.href=\'{url}\'">'
                    f"<strong>{ref_name}</strong></div>"
                )
            html_parts.append("</div></div>")
```

- [ ] **Step 3: Run all tests**

```bash
cd backend && .venv/bin/pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
cd backend && git add templates/game_detail.html app/main.py
git commit -m "feat: clickable referee names + referee global search results"
```

---

## Task 5: Staff DB model

**Files:**
- Modify: `backend/app/models/db_models.py`

- [ ] **Step 1: Add Staff model to db_models.py**

Add after the `PlayerStatistics` class (around line 460), before `SyncStatus`:

```python
class Staff(Base):
    """Coaching staff per team per season, indexed from the Swiss Unihockey API."""

    __tablename__ = "staff"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)         # person_id from API
    season_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("seasons.id"), primary_key=True
    )
    team_id: Mapped[int] = mapped_column(Integer, nullable=False)
    team_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    league_db_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    role: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_updated: Mapped[Optional[datetime]] = mapped_column(DateTime, default=_utcnow)
```

The composite primary key `(id, season_id)` allows the same person to appear across seasons. `session.merge()` will upsert correctly.

- [ ] **Step 2: Verify the model creates its table**

```bash
cd backend && DATABASE_PATH=:memory: .venv/bin/python3 -c "
from app.services.database import get_database_service
db = get_database_service()
db.ensure_tables_exist()
from app.models.db_models import Staff
print('Staff table created OK')
"
```

Expected: `Staff table created OK`

- [ ] **Step 3: Run all tests (migrations are auto-applied)**

```bash
cd backend && .venv/bin/pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
cd backend && git add app/models/db_models.py
git commit -m "feat: add Staff DB model for coaching staff"
```

---

## Task 6: get_team_staff API client method

**Files:**
- Modify: `backend/app/services/api_client.py`

- [ ] **Step 1: Add get_team_staff after get_team_stats**

Find `get_team_stats` (~line 340):
```python
    def get_team_stats(self, team_id: int) -> Dict[str, Any]:
        return self._make_request(f"/api/teams/{team_id}/statistics", {})
```

Add immediately after:
```python
    def get_team_staff(self, team_id: int) -> Dict[str, Any]:
        """Fetch coaching staff for a team. Returns list of staff members."""
        return self._make_request(f"/api/teams/{team_id}/staff", {})
```

- [ ] **Step 2: Verify no import or syntax errors**

```bash
cd backend && .venv/bin/python3 -c "from app.services.api_client import SwissUnihockeyClient; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
cd backend && git add app/services/api_client.py
git commit -m "feat: add get_team_staff to SwissUnihockeyClient"
```

---

## Task 7: index_team_staff in data_indexer.py

**Files:**
- Modify: `backend/app/services/data_indexer.py`
- Test: `backend/tests/test_data_indexer.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_data_indexer.py` (find the existing test class structure and add a new class):

```python
class TestIndexTeamStaff:
    """Test index_team_staff upserts Staff rows correctly."""

    def test_indexes_headcoach_and_assistantcoach(self, db_session):
        from unittest.mock import MagicMock, patch
        from app.services.data_indexer import DataIndexer
        from app.models.db_models import Staff, Season, Team

        db_session.merge(Season(id=2025, text="2024/25", highlighted=True))
        db_session.merge(Team(id=101, season_id=2025, name="Test Team"))
        db_session.flush()

        mock_staff_response = {
            "data": [
                {"person_id": 201, "first_name": "Hans", "last_name": "Meier", "role": "Headcoach"},
                {"person_id": 202, "first_name": "Kurt", "last_name": "Müller", "role": "Assistantcoach"},
                {"person_id": 203, "first_name": "Beat", "last_name": "Keller", "role": "Physiotherapist"},
            ]
        }

        indexer = DataIndexer.__new__(DataIndexer)
        indexer.client = MagicMock()
        indexer.client.get_team_staff.return_value = mock_staff_response

        indexer.index_team_staff(101, 2025, db_session)

        staff_rows = db_session.query(Staff).filter(Staff.team_id == 101).all()
        roles = {s.role for s in staff_rows}
        # Only Headcoach and Assistantcoach are indexed; Physiotherapist is skipped
        assert "Headcoach" in roles
        assert "Assistantcoach" in roles
        assert "Physiotherapist" not in roles
        assert len(staff_rows) == 2

    def test_upserts_existing_staff(self, db_session):
        from unittest.mock import MagicMock
        from app.services.data_indexer import DataIndexer
        from app.models.db_models import Staff, Season, Team

        db_session.merge(Season(id=2025, text="2024/25", highlighted=True))
        db_session.merge(Team(id=102, season_id=2025, name="Team 2"))
        db_session.flush()

        # Seed existing staff row
        db_session.merge(Staff(id=301, season_id=2025, team_id=102,
                               first_name="Old", last_name="Name", role="Headcoach"))
        db_session.flush()

        mock_staff_response = {
            "data": [
                {"person_id": 301, "first_name": "New", "last_name": "Name", "role": "Headcoach"},
            ]
        }
        indexer = DataIndexer.__new__(DataIndexer)
        indexer.client = MagicMock()
        indexer.client.get_team_staff.return_value = mock_staff_response

        indexer.index_team_staff(102, 2025, db_session)
        db_session.flush()

        s = db_session.query(Staff).filter(Staff.id == 301, Staff.season_id == 2025).one()
        assert s.first_name == "New"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && .venv/bin/pytest tests/test_data_indexer.py::TestIndexTeamStaff -v
```

Expected: FAIL — `AttributeError: 'DataIndexer' has no attribute 'index_team_staff'`.

- [ ] **Step 3: Add index_team_staff to data_indexer.py**

Find `index_teams_for_club` method (around line 656) and add `index_team_staff` as a new method of the `DataIndexer` class. Place it near the other per-team indexing methods:

```python
    def index_team_staff(
        self, team_id: int, season_id: int, session
    ) -> None:
        """Fetch and upsert coaching staff for *team_id* in *season_id*.

        Only indexes Headcoach and Assistantcoach roles — skips physiotherapists
        and other support staff.
        """
        from app.models.db_models import Staff

        _INDEXED_ROLES = {"headcoach", "assistantcoach"}

        try:
            data = self.client.get_team_staff(team_id)
        except Exception as exc:
            logger.warning("get_team_staff(%s) failed: %s", team_id, exc)
            return

        staff_list = data.get("data") or []
        for member in staff_list:
            role = (member.get("role") or "").strip()
            if role.lower() not in _INDEXED_ROLES:
                continue
            person_id = member.get("person_id")
            if not person_id:
                continue
            staff_row = Staff(
                id=int(person_id),
                season_id=season_id,
                team_id=team_id,
                first_name=member.get("first_name") or None,
                last_name=member.get("last_name") or None,
                role=role,
            )
            session.merge(staff_row)
```

- [ ] **Step 4: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_data_indexer.py::TestIndexTeamStaff -v
```

Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/services/data_indexer.py tests/test_data_indexer.py
git commit -m "feat: add index_team_staff to DataIndexer"
```

---

## Task 8: get_coach_detail + extend get_team_detail with head_coach

**Files:**
- Modify: `backend/app/services/stats_service.py`
- Test: `backend/tests/test_stats_service.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_stats_service.py`:

```python
class TestGetCoachDetail:
    """Test get_coach_detail returns correct structure."""

    def _seed_coach(self, session):
        from app.models.db_models import Staff, Season, Team
        session.merge(Season(id=2025, text="2024/25", highlighted=True))
        session.merge(Season(id=2024, text="2023/24", highlighted=False))
        session.merge(Team(id=201, season_id=2025, name="Team X"))
        session.flush()
        session.merge(Staff(
            id=401, season_id=2025, team_id=201, team_name="Team X",
            first_name="Anna", last_name="Coach", role="Headcoach",
        ))
        session.merge(Staff(
            id=401, season_id=2024, team_id=201, team_name="Team X",
            first_name="Anna", last_name="Coach", role="Headcoach",
        ))

    def test_returns_coach_dict(self):
        from app.services.stats_service import get_coach_detail
        from app.services.database import get_database_service
        db = get_database_service()
        with db.session_scope() as session:
            self._seed_coach(session)
        with db.session_scope() as session:
            result = get_coach_detail(401, session)
        assert result is not None
        assert result["name"] == "Anna Coach"
        assert result["person_id"] == 401

    def test_seasons_ordered_desc(self):
        from app.services.stats_service import get_coach_detail
        from app.services.database import get_database_service
        db = get_database_service()
        with db.session_scope() as session:
            result = get_coach_detail(401, session)
        season_ids = [s["season_id"] for s in result["seasons"]]
        assert season_ids == sorted(season_ids, reverse=True)

    def test_unknown_coach_returns_none(self):
        from app.services.stats_service import get_coach_detail
        from app.services.database import get_database_service
        db = get_database_service()
        with db.session_scope() as session:
            result = get_coach_detail(999999, session)
        assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && .venv/bin/pytest tests/test_stats_service.py::TestGetCoachDetail -v
```

Expected: FAIL — `ImportError: cannot import name 'get_coach_detail'`.

- [ ] **Step 3: Add get_coach_detail to stats_service.py**

Add after `get_referee_games`:

```python
def get_coach_detail(person_id: int, session) -> dict | None:
    """Return coaching history for a staff person.

    Args:
        person_id: Staff.id (person_id from API).
        session: active SQLAlchemy session.

    Returns dict or None if person not found.
    """
    from app.models.db_models import Staff

    rows = (
        session.query(Staff)
        .filter(Staff.id == person_id)
        .order_by(Staff.season_id.desc())
        .all()
    )
    if not rows:
        return None
    latest = rows[0]
    name = " ".join(
        part for part in [latest.first_name, latest.last_name] if part
    ).strip() or f"Coach {person_id}"

    season_texts = {
        r[0]: r[1]
        for r in session.query(Season.id, Season.text)
        .filter(Season.id.in_([r.season_id for r in rows]))
        .all()
    }

    return {
        "person_id": person_id,
        "name": name,
        "role": latest.role,
        "seasons": [
            {
                "season_id": r.season_id,
                "season_text": season_texts.get(r.season_id) or str(r.season_id),
                "team_name": r.team_name or "",
                "team_db_id": r.team_id,
                "league_db_id": r.league_db_id,
                "role": r.role,
            }
            for r in rows
        ],
    }
```

Also add `Season` to the imports at the top of `stats_service.py` if not already present (it is — used in `get_player_detail`).

- [ ] **Step 4: Extend get_team_detail to include head_coach**

In `get_team_detail`, after the roster is built and before the `return {}` / result dict is assembled, add a coach lookup:

```python
        # Head coach lookup
        from app.models.db_models import Staff as _Staff
        _head_coach_row = (
            session.query(_Staff)
            .filter(
                _Staff.team_id == team_id,
                _Staff.season_id == season_id,
                func.lower(_Staff.role) == "headcoach",
            )
            .first()
        )
        head_coach = None
        if _head_coach_row:
            _cn = " ".join(
                p for p in [_head_coach_row.first_name, _head_coach_row.last_name] if p
            ).strip()
            head_coach = {"person_id": _head_coach_row.id, "name": _cn or f"Coach {_head_coach_row.id}"}
```

Then add `"head_coach": head_coach,` to the returned dict.

- [ ] **Step 5: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_stats_service.py::TestGetCoachDetail -v
```

Expected: 3 PASSED.

- [ ] **Step 6: Commit**

```bash
cd backend && git add app/services/stats_service.py tests/test_stats_service.py
git commit -m "feat: add get_coach_detail and head_coach to get_team_detail"
```

---

## Task 9: Coach detail route and template

**Files:**
- Modify: `backend/app/main.py`
- Create: `backend/templates/coach_detail.html`

- [ ] **Step 1: Add coach_detail route to main.py**

Add alongside the referee_detail route:

```python
@app.get("/{locale}/coach/{person_id:int}", response_class=HTMLResponse)
async def coach_detail(locale: str, person_id: int, request: Request):
    """Coach detail page — shows all teams coached across seasons."""
    from app.services.stats_service import get_coach_detail
    from app.services.database import get_database_service
    t = get_translations(locale)
    db = get_database_service()
    with db.session_scope() as session:
        coach = get_coach_detail(person_id, session)
    if coach is None:
        raise HTTPException(status_code=404, detail="Coach not found")
    return templates.TemplateResponse(
        "coach_detail.html",
        {"request": request, "locale": locale, "t": t, "coach": coach},
    )
```

- [ ] **Step 2: Create coach_detail.html**

Create `backend/templates/coach_detail.html`:

```html
{% extends "base.html" %}
{% block title %}{{ t.coach.page_title }} — {{ coach.name }}{% endblock %}

{% block content %}
<div class="container page-content">
  <div style="margin-bottom:1.5rem;">
    <h1 style="font-size:1.75rem;font-weight:700;margin-bottom:.25rem;">🎯 {{ coach.name }}</h1>
    <p style="color:var(--gray-500);font-size:.9rem;">
      {% if coach.role and coach.role | lower == 'headcoach' %}{{ t.coach.head_coach }}
      {% elif coach.role and coach.role | lower == 'assistantcoach' %}{{ t.coach.assistant_coach }}
      {% elif coach.role %}{{ coach.role }}{% endif %}
    </p>
  </div>

  {% if coach.seasons %}
  <div class="section-block">
    <div class="section-block-header">
      <h2 class="section-block-title">{{ t.coach.season_history }}</h2>
    </div>
    <div class="table-scroll">
      <table class="data-table">
        <thead>
          <tr>
            <th>{{ t.table.season }}</th>
            <th>{{ t.table.team }}</th>
            <th>{{ t.table.league }}</th>
            <th>Role</th>
          </tr>
        </thead>
        <tbody>
          {% for s in coach.seasons %}
          <tr>
            <td style="font-weight:500;">{{ s.season_text }}</td>
            <td>
              {% if s.team_db_id %}<a href="/{{ locale }}/team/{{ s.team_db_id }}?season={{ s.season_id }}" class="link-text">{{ s.team_name }}</a>{% else %}{{ s.team_name }}{% endif %}
            </td>
            <td style="font-size:.8rem;color:var(--gray-500);">
              {% if s.league_db_id %}<a href="/{{ locale }}/league/{{ s.league_db_id }}" class="link-text">—</a>{% else %}—{% endif %}
            </td>
            <td style="font-size:.85rem;color:var(--gray-500);">{{ s.role }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
  {% else %}
  <div class="empty-state-center">
    <p class="empty-state-icon">🎯</p>
    <p>{{ t.coach.no_seasons }}</p>
  </div>
  {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 3: Run all tests**

```bash
cd backend && .venv/bin/pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
cd backend && git add app/main.py templates/coach_detail.html
git commit -m "feat: add coach detail page and route"
```

---

## Task 10: Show coach in team_detail.html + game_detail.html + global search

**Files:**
- Modify: `backend/templates/team_detail.html`
- Modify: `backend/templates/game_detail.html`
- Modify: `backend/app/main.py` (global search)

- [ ] **Step 1: Add head coach line in team_detail.html**

Find the team info header section (around the league name / season display area). Look for the venue or league line in the team header — search for `team.league_name` or `team.season_name` in `team_detail.html`. Add after the league/season display:

```html
      {% if team.head_coach %}
      <div style="font-size:.8rem;color:var(--gray-500);margin-top:.25rem;">
        🎯 {{ t.coach.head_coach }}:
        <a href="/{{ locale }}/coach/{{ team.head_coach.person_id }}" class="link-text">{{ team.head_coach.name }}</a>
      </div>
      {% endif %}
```

To find the exact insertion point, search for the line with `team.league_name` or `team.name` in the header `<div>` near the top of the team detail content (not inside the roster table).

- [ ] **Step 2: Add coach names in game_detail.html**

Find the referee display area (around line 455). After the referee line, add:

```html
    {% if game.home_coach or game.away_coach %}
    <div class="gd-meta-venue" style="font-size:.75rem;color:var(--gray-500);">🎯
      {% if game.home_coach %}<a href="/{{ locale }}/coach/{{ game.home_coach.person_id }}" style="color:inherit;text-decoration:none;" onmouseover="this.style.textDecoration='underline'" onmouseout="this.style.textDecoration='none'">{{ game.home_coach.name }}</a>{% endif %}{% if game.home_coach and game.away_coach %} · {% endif %}{% if game.away_coach %}<a href="/{{ locale }}/coach/{{ game.away_coach.person_id }}" style="color:inherit;text-decoration:none;" onmouseover="this.style.textDecoration='underline'" onmouseout="this.style.textDecoration='none'">{{ game.away_coach.name }}</a>{% endif %}
    </div>
    {% endif %}
```

**Backend change required:** In `stats_service.py`, find `get_game_box_score` (around line 2953). In the returned dict, add `home_coach` and `away_coach` by looking up `Staff` for home/away team + game season:

```python
        # Coach lookup for home and away teams
        from app.models.db_models import Staff as _StaffModel
        from sqlalchemy import func as _func

        def _get_head_coach(team_id, season_id):
            row = (
                session.query(_StaffModel)
                .filter(
                    _StaffModel.team_id == team_id,
                    _StaffModel.season_id == season_id,
                    _func.lower(_StaffModel.role) == "headcoach",
                )
                .first()
            )
            if not row:
                return None
            name = " ".join(p for p in [row.first_name, row.last_name] if p).strip()
            return {"person_id": row.id, "name": name or f"Coach {row.id}"}

        home_coach = _get_head_coach(game.home_team_id, game.season_id)
        away_coach = _get_head_coach(game.away_team_id, game.season_id)
```

Add `"home_coach": home_coach, "away_coach": away_coach,` to the returned box score dict.

Find the returned dict in `get_game_box_score` — search for `"referee_1"` in the returned dict and add the coach fields near it.

- [ ] **Step 3: Add coach results to global search in main.py**

In `universal_search`, after the referee section, add:

```python
        # --- Coaches ---
        from app.models.db_models import Staff as _StaffModel
        from sqlalchemy import func as _sfunc

        coach_matches = (
            session.query(_StaffModel)
            .filter(
                or_(
                    (_sfunc.lower(_StaffModel.first_name) + " " + _sfunc.lower(_StaffModel.last_name)).ilike(f"%{q.lower()}%"),
                    _StaffModel.last_name.ilike(f"%{q}%"),
                    _StaffModel.first_name.ilike(f"%{q}%"),
                ),
                _StaffModel.role.isnot(None),
            )
            .order_by(_StaffModel.season_id.desc())
            .limit(5)
            .all()
        )
        seen_coach_ids: set[int] = set()
        unique_coaches = []
        for cm in coach_matches:
            if cm.id not in seen_coach_ids:
                seen_coach_ids.add(cm.id)
                unique_coaches.append(cm)
        if unique_coaches:
            html_parts.append(
                '<div class="search-category"><h3>🎯 Coaches</h3><div class="search-items">'
            )
            for cm in unique_coaches:
                cname = " ".join(p for p in [cm.first_name, cm.last_name] if p).strip()
                crole = cm.role or ""
                html_parts.append(
                    f'<div class="search-item" onclick="window.location.href=\'/{locale}/coach/{cm.id}\'">'
                    f'<span class="search-item-main"><strong>{cname}</strong>'
                    f'<span class="search-item-subtitle">{crole}</span></span></div>'
                )
            html_parts.append("</div></div>")
```

- [ ] **Step 4: Run all tests**

```bash
cd backend && .venv/bin/pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
cd backend && git add templates/team_detail.html templates/game_detail.html app/main.py app/services/stats_service.py
git commit -m "feat: show coaches in team/game detail and global search"
```
