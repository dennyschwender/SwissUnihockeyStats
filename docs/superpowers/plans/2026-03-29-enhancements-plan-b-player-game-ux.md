# Enhancements Plan B — Player & Game UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapsible per-season career history for players, and a richer game timeline with score/penalty labels, structured tooltip, and horizontal-scrollable mobile view.

**Architecture:** Two independent features. (1) `get_player_detail` adds `career_by_season` (grouped + aggregated) alongside the existing flat `career` list; `player_detail.html` replaces the flat table with Alpine collapsible rows. (2) `build_timeline_events` exposes `score` (goals) and `minutes`/`infraction` (penalties) already computed in the goals list; `game_detail.html` gets dot labels via vertical CSS text, a structured multi-field tooltip, and a mobile CSS change from hidden to horizontally-scrollable.

**Tech Stack:** Python/SQLAlchemy (`stats_service.py`), Jinja2 + Alpine.js (templates), pytest

---

## File Map

| File | Change |
|---|---|
| `backend/app/services/stats_service.py` | `get_player_detail`: add `career_by_season`; `build_timeline_events`: add `score`/`minutes`/`infraction` to event dicts |
| `backend/templates/player_detail.html` | Replace flat career table with per-season collapsible Alpine rows |
| `backend/templates/game_detail.html` | Dot labels (CSS + span), structured tooltip, mobile CSS |
| `backend/tests/test_stats_service.py` | Tests for `career_by_season` grouping + timeline event fields |

---

## Task 1: Add career_by_season to get_player_detail

**Files:**
- Modify: `backend/app/services/stats_service.py` (around line 2278–2310)
- Test: `backend/tests/test_stats_service.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_stats_service.py`:

```python
class TestCareerBySeason:
    """Test career_by_season grouping in get_player_detail."""

    def _seed_player_with_two_seasons(self, session):
        from app.models.db_models import Player, Season, PlayerStatistics
        s1 = Season(id=2024, text="2023/24", highlighted=False)
        s2 = Season(id=2025, text="2024/25", highlighted=True)
        session.merge(s1)
        session.merge(s2)
        p = Player(person_id=9001, full_name="Test Player")
        session.merge(p)
        session.flush()
        # Two rows in 2025 (two teams/leagues), one row in 2024
        session.add(PlayerStatistics(
            player_id=9001, season_id=2025,
            league_abbrev="NLA", team_name="Team A",
            games_played=10, goals=5, assists=3, points=8, penalty_minutes=4,
        ))
        session.add(PlayerStatistics(
            player_id=9001, season_id=2025,
            league_abbrev="NLB", team_name="Team B",
            games_played=5, goals=1, assists=2, points=3, penalty_minutes=2,
        ))
        session.add(PlayerStatistics(
            player_id=9001, season_id=2024,
            league_abbrev="NLA", team_name="Team A",
            games_played=20, goals=10, assists=8, points=18, penalty_minutes=6,
        ))

    def test_career_by_season_present(self):
        from app.services.database import get_database_service
        db = get_database_service()
        with db.session_scope() as session:
            self._seed_player_with_two_seasons(session)
        result = get_player_detail(person_id=9001)
        assert "career_by_season" in result

    def test_career_by_season_ordered_desc(self):
        result = get_player_detail(person_id=9001)
        seasons = result["career_by_season"]
        assert len(seasons) == 2
        assert seasons[0]["season_id"] == 2025
        assert seasons[1]["season_id"] == 2024

    def test_career_by_season_totals_aggregated(self):
        result = get_player_detail(person_id=9001)
        season_2025 = result["career_by_season"][0]
        assert season_2025["totals"]["gp"] == 15   # 10 + 5
        assert season_2025["totals"]["g"] == 6     # 5 + 1
        assert season_2025["totals"]["a"] == 5     # 3 + 2
        assert season_2025["totals"]["pts"] == 11  # 8 + 3
        assert len(season_2025["rows"]) == 2

    def test_career_by_season_single_row_season(self):
        result = get_player_detail(person_id=9001)
        season_2024 = result["career_by_season"][1]
        assert len(season_2024["rows"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && .venv/bin/pytest tests/test_stats_service.py::TestCareerBySeason -v
```

Expected: FAIL — `AssertionError: 'career_by_season' not in result`.

- [ ] **Step 3: Add career_by_season to get_player_detail**

In `stats_service.py`, find the block after `career.sort(...)` and the `for r in career: r.pop("_tier", None)` loop (around line 2278). After these lines and before the career totals computation, insert:

```python
        # Build career_by_season: group career rows by season_id
        _season_groups: dict[int, list[dict]] = {}
        for r in career:
            _season_groups.setdefault(r["season_id"], []).append(r)

        career_by_season: list[dict] = []
        for _sid in sorted(_season_groups.keys(), reverse=True):
            _rows = _season_groups[_sid]
            _sgp  = sum((r.get("gp")  or 0) for r in _rows)
            _sg   = sum((r.get("g")   or 0) for r in _rows)
            _sa   = sum((r.get("a")   or 0) for r in _rows)
            _spts = sum((r.get("pts") or 0) for r in _rows)
            _spim = sum((r.get("pim") or 0) for r in _rows)
            career_by_season.append(
                {
                    "season_id": _sid,
                    "season_text": _rows[0]["season_text"],
                    "totals": {
                        "gp":  _sgp,
                        "g":   _sg,
                        "a":   _sa,
                        "pts": _spts,
                        "pim": _spim,
                        "ppg": _compute_ppg(_spts, _sgp),
                    },
                    "rows": _rows,
                }
            )
```

Then find the `result = { ... }` dict (around line 2302) and add `"career_by_season": career_by_season,` to it:

```python
        result = {
            "person_id": player.person_id,
            "name": player.full_name or f"Player {player.person_id}",
            "first_name": player.first_name or "",
            "last_name": player.last_name or "",
            "year_of_birth": player.year_of_birth,
            "career": career,
            "career_by_season": career_by_season,
            "totals": totals,
            ...
        }
```

- [ ] **Step 4: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_stats_service.py::TestCareerBySeason -v
```

Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/services/stats_service.py tests/test_stats_service.py
git commit -m "feat: add career_by_season grouping to get_player_detail"
```

---

## Task 2: Collapsible career table in player_detail.html

**Files:**
- Modify: `backend/templates/player_detail.html` (lines 59–118)

- [ ] **Step 1: Replace the career section with collapsible Alpine rows**

Find the entire `<!-- Season History (collapsible) -->` section (lines 59–124) and replace it with:

```html
  <!-- Season History (collapsible per season) -->
  {% if player.career_by_season %}
  <div class="section-block">
    <div class="section-block-header">
      <h2 class="section-block-title">{{ t.player.season_history }}</h2>
    </div>
    <div class="table-scroll">
      <table class="data-table">
        <thead>
          <tr>
            <th>{{ t.table.season }}</th>
            <th>{{ t.table.league }}</th>
            <th>{{ t.table.team }}</th>
            <th class="col-narrow">GP</th>
            <th class="col-narrow">G</th>
            <th class="col-narrow">A</th>
            <th class="col-narrow" style="font-weight:700;">PTS</th>
            <th class="col-narrow">PIM</th>
            <th class="col-narrow">{{ t.player.ppg }}</th>
            <th class="col-narrow" style="width:1.5rem;"></th>
          </tr>
        </thead>
        <tbody>
          {% for season in player.career_by_season %}
          {% set multi = season.rows | length > 1 %}
          <tr x-data="{ open: {{ 'true' if loop.first else 'false' }} }"
              style="background:var(--gray-50);border-top:1px solid var(--gray-200);cursor:{% if multi %}pointer{% else %}default{% endif %};"
              {% if multi %}@click="open = !open"{% endif %}>
            <td style="font-weight:600;">
              <a href="/{{ locale }}/leagues?season={{ season.season_id }}" class="link-inherit" @click.stop>{{ season.season_text }}</a>
            </td>
            <td style="font-size:.8rem;color:var(--gray-500);">
              {% if not multi and season.rows[0].league_db_id %}
                <a href="/{{ locale }}/league/{{ season.rows[0].league_db_id }}" class="link-inherit" @click.stop>{{ season.rows[0].league }}</a>
              {% elif not multi %}{{ season.rows[0].league }}
              {% else %}–
              {% endif %}
            </td>
            <td style="color:var(--gray-600);">
              {% if not multi and season.rows[0].team_db_id %}
                <a href="/{{ locale }}/team/{{ season.rows[0].team_db_id }}?season={{ season.season_id }}" class="link-inherit" @click.stop>{{ season.rows[0].team_name }}</a>
              {% elif not multi %}{{ season.rows[0].team_name }}
              {% else %}–
              {% endif %}
            </td>
            <td class="col-narrow">{{ season.totals.gp }}</td>
            <td class="col-narrow">{{ season.totals.g }}</td>
            <td class="col-narrow">{{ season.totals.a }}</td>
            <td class="col-narrow" style="font-weight:700;">{{ season.totals.pts }}</td>
            <td class="col-narrow">{{ season.totals.pim }}</td>
            <td class="col-narrow" style="color:var(--gray-500);">{{ season.totals.ppg if season.totals.ppg is not none else '–' }}</td>
            <td class="col-narrow" style="text-align:center;font-size:.7rem;color:var(--gray-400);">
              {% if multi %}<span x-text="open ? '▼' : '▶'"></span>{% endif %}
            </td>
          </tr>
          {% if multi %}
            {% for row in season.rows %}
            <tr x-data x-show="{{ 'true' if loop.first else 'false' }}"
                x-cloak
                style="background:var(--white);"
                x-bind:style="$el.closest('tr').previousElementSibling?.__x?.$data?.open ? '' : 'display:none'"
                x-effect="$el.style.display = document.querySelector('[x-data*=\'open\']') ? '' : ''">
            </tr>
            {% endfor %}
          {% endif %}
          {% endfor %}
```

Wait — the Alpine `x-show` for sub-rows must reference the parent row's `open` state. The cleanest approach in Jinja2+Alpine is to wrap each season in a `<tbody x-data="{ open: ... }">`:

Replace with this cleaner approach:

```html
  <!-- Season History (collapsible per season) -->
  {% if player.career_by_season %}
  <div class="section-block">
    <div class="section-block-header">
      <h2 class="section-block-title">{{ t.player.season_history }}</h2>
    </div>
    <div class="table-scroll">
      <table class="data-table">
        <thead>
          <tr>
            <th>{{ t.table.season }}</th>
            <th>{{ t.table.league }}</th>
            <th>{{ t.table.team }}</th>
            <th class="col-narrow">GP</th>
            <th class="col-narrow">G</th>
            <th class="col-narrow">A</th>
            <th class="col-narrow" style="font-weight:700;">PTS</th>
            <th class="col-narrow">PIM</th>
            <th class="col-narrow">{{ t.player.ppg }}</th>
            <th class="col-narrow" style="width:1.5rem;"></th>
          </tr>
        </thead>
        {% for season in player.career_by_season %}
        {% set multi = season.rows | length > 1 %}
        <tbody x-data="{ open: {{ 'true' if loop.first else 'false' }} }">
          <!-- Season summary row -->
          <tr style="background:var(--gray-50);border-top:2px solid var(--gray-200);"
              {% if multi %}@click="open = !open" style="background:var(--gray-50);border-top:2px solid var(--gray-200);cursor:pointer;"{% endif %}>
            <td style="font-weight:600;">
              <a href="/{{ locale }}/leagues?season={{ season.season_id }}" class="link-inherit" @click.stop>{{ season.season_text }}</a>
            </td>
            <td style="font-size:.8rem;color:var(--gray-500);">
              {% if not multi and season.rows[0].league_db_id %}
                <a href="/{{ locale }}/league/{{ season.rows[0].league_db_id }}" class="link-inherit" @click.stop>{{ season.rows[0].league }}</a>
              {% elif not multi %}{{ season.rows[0].league }}{% else %}–{% endif %}
            </td>
            <td style="color:var(--gray-600);">
              {% if not multi and season.rows[0].team_db_id %}
                <a href="/{{ locale }}/team/{{ season.rows[0].team_db_id }}?season={{ season.season_id }}" class="link-inherit" @click.stop>{{ season.rows[0].team_name }}</a>
              {% elif not multi %}{{ season.rows[0].team_name }}{% else %}–{% endif %}
            </td>
            <td class="col-narrow">{{ season.totals.gp }}</td>
            <td class="col-narrow">{{ season.totals.g }}</td>
            <td class="col-narrow">{{ season.totals.a }}</td>
            <td class="col-narrow" style="font-weight:700;">{{ season.totals.pts }}</td>
            <td class="col-narrow">{{ season.totals.pim }}</td>
            <td class="col-narrow" style="color:var(--gray-500);">{{ season.totals.ppg if season.totals.ppg is not none else '–' }}</td>
            <td class="col-narrow" style="text-align:center;font-size:.7rem;color:var(--gray-400);">
              {% if multi %}<span x-text="open ? '▼' : '▶'"></span>{% endif %}
            </td>
          </tr>
          <!-- Sub-rows (only shown when expanded) -->
          {% if multi %}
          {% for row in season.rows %}
          <tr x-show="open" x-cloak style="background:var(--white);">
            <td style="font-size:.8rem;color:var(--gray-500);padding-left:1.5rem;">
              <a href="/{{ locale }}/leagues?season={{ row.season_id }}" class="link-inherit">{{ row.season_text }}</a>
            </td>
            <td style="font-size:.8rem;color:var(--gray-500);">
              {% if row.league_db_id %}<a href="/{{ locale }}/league/{{ row.league_db_id }}" class="link-inherit">{{ row.league }}</a>{% else %}{{ row.league }}{% endif %}
            </td>
            <td style="color:var(--gray-600);font-size:.85rem;">
              {% if row.team_db_id %}<a href="/{{ locale }}/team/{{ row.team_db_id }}?season={{ row.season_id }}" class="link-inherit">{{ row.team_name }}</a>{% else %}{{ row.team_name }}{% endif %}
            </td>
            <td class="col-narrow">{{ row.gp }}</td>
            <td class="col-narrow">{{ row.g }}</td>
            <td class="col-narrow">{{ row.a }}</td>
            <td class="col-narrow" style="font-weight:700;">{{ row.pts }}</td>
            <td class="col-narrow">{{ row.pim }}</td>
            <td class="col-narrow" style="color:var(--gray-500);">{{ row.ppg if row.ppg is not none else '–' }}</td>
            <td></td>
          </tr>
          {% endfor %}
          {% endif %}
        </tbody>
        {% endfor %}
        <!-- Totals row -->
        <tfoot>
          <tr style="background:var(--gray-50);border-top:2px solid var(--gray-200);font-weight:700;">
            <td colspan="3">{{ t.player.career_totals }}</td>
            <td class="col-narrow">{{ player.totals.gp }}</td>
            <td class="col-narrow">{{ player.totals.g }}</td>
            <td class="col-narrow">{{ player.totals.a }}</td>
            <td class="col-narrow">{{ player.totals.pts }}</td>
            <td class="col-narrow">{{ player.totals.pim }}</td>
            <td class="col-narrow" style="color:var(--gray-500);">{{ player.totals.ppg if player.totals.ppg is not none else '–' }}</td>
            <td></td>
          </tr>
        </tfoot>
      </table>
    </div>
  </div>
  {% else %}
  <div class="empty-state-center">
    <p class="empty-state-icon">📊</p>
    <p>No statistics on record for this player.</p>
  </div>
  {% endif %}
```

- [ ] **Step 2: Run tests**

```bash
cd backend && .venv/bin/pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
cd backend && git add templates/player_detail.html
git commit -m "feat: collapsible per-season career history in player detail"
```

---

## Task 3: Add score/minutes/infraction to build_timeline_events

**Files:**
- Modify: `backend/app/services/stats_service.py` (lines 2915–2947)
- Test: `backend/tests/test_stats_service.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_stats_service.py`:

```python
class TestBuildTimelineEvents:
    """Test build_timeline_events includes score, minutes, infraction fields."""

    def _make_goal(self, period, time, score, team="Home"):
        return {"period": period, "time": time, "score": score, "team": team, "player": "Player A"}

    def _make_penalty(self, period, time, minutes, infraction, team="Home"):
        return {"period": period, "time": time, "minutes": minutes,
                "infraction": infraction, "team": team, "player": "Player B"}

    def test_goal_event_includes_score(self):
        from app.services.stats_service import build_timeline_events
        goals = [self._make_goal(1, "05:00", "1:0")]
        events, _ = build_timeline_events(goals, [], "Home", "Away")
        goal_ev = next(e for e in events if e["kind"] == "goal")
        assert "score" in goal_ev
        assert goal_ev["score"] == "1:0"

    def test_penalty_event_includes_minutes_and_infraction(self):
        from app.services.stats_service import build_timeline_events
        pens = [self._make_penalty(1, "03:00", 2, "Hooking")]
        events, _ = build_timeline_events([], pens, "Home", "Away")
        pen_ev = next(e for e in events if e["kind"] == "penalty")
        assert "minutes" in pen_ev
        assert pen_ev["minutes"] == 2
        assert "infraction" in pen_ev
        assert pen_ev["infraction"] == "Hooking"

    def test_penalty_missing_infraction_defaults_to_empty_string(self):
        from app.services.stats_service import build_timeline_events
        pens = [{"period": 1, "time": "03:00", "minutes": 5, "team": "Away", "player": "X"}]
        events, _ = build_timeline_events([], pens, "Home", "Away")
        pen_ev = events[0]
        assert pen_ev["infraction"] == ""

    def test_goal_missing_score_defaults_to_empty_string(self):
        from app.services.stats_service import build_timeline_events
        goals = [{"period": 1, "time": "05:00", "team": "Home", "player": "X"}]
        events, _ = build_timeline_events(goals, [], "Home", "Away")
        goal_ev = events[0]
        assert goal_ev["score"] == ""
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && .venv/bin/pytest tests/test_stats_service.py::TestBuildTimelineEvents -v
```

Expected: FAIL — `KeyError: 'score'` or `AssertionError`.

- [ ] **Step 3: Add score to goal events and minutes/infraction to penalty events**

In `build_timeline_events` (around line 2915), find the goal `events.append({...})` block and add `"score"`:

```python
        events.append(
            {
                "id": f"goal-{i}",
                "kind": "goal",
                "team_side": _team_side(team),
                "pct": round(pct, 4),
                "label": label,
                "score": g.get("score", ""),
            }
        )
```

Find the penalty `events.append({...})` block and add `"minutes"` and `"infraction"`:

```python
        events.append(
            {
                "id": f"pen-{i}",
                "kind": "penalty",
                "team_side": _team_side(team),
                "pct": round(pct, 4),
                "label": label,
                "minutes": minutes,
                "infraction": infraction,
            }
        )
```

- [ ] **Step 4: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_stats_service.py::TestBuildTimelineEvents -v
```

Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/services/stats_service.py tests/test_stats_service.py
git commit -m "feat: add score/minutes/infraction to build_timeline_events"
```

---

## Task 4: Timeline dot labels, structured tooltip, mobile CSS

**Files:**
- Modify: `backend/templates/game_detail.html`

- [ ] **Step 1: Update .tl-marker CSS to accommodate label text**

Find the `.tl-marker` CSS block (~line 310):
```css
  .tl-marker {
    position: absolute;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    border: 2px solid var(--card-bg, white);
    cursor: pointer;
    transform: translateX(-50%);
    transition: transform .1s;
  }
  .tl-marker.goal { top: calc(50% - 14px); }
  .tl-marker.penalty {
    top: calc(50% + 6px);
    border-radius: 2px;
    width: 8px; height: 8px;
  }
```

Replace with:
```css
  .tl-marker {
    position: absolute;
    width: 10px;
    height: 20px;
    border-radius: 3px;
    border: 2px solid var(--card-bg, white);
    cursor: pointer;
    transform: translateX(-50%);
    transition: transform .1s;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
  }
  .tl-marker:hover { transform: translateX(-50%) scale(1.4); }
  .tl-marker.goal { top: calc(50% - 18px); border-radius: 50% 50% 3px 3px; }
  .tl-marker.penalty {
    top: calc(50% + 4px);
    border-radius: 2px;
    width: 8px; height: 16px;
  }
  .tl-marker-label {
    writing-mode: vertical-rl;
    font-size: .5rem;
    font-weight: 700;
    color: white;
    pointer-events: none;
    line-height: 1;
    text-shadow: none;
    overflow: hidden;
    max-height: 100%;
  }
```

- [ ] **Step 2: Add label span inside each tl-marker**

Find the event markers template block (~line 554):
```html
      <!-- Event markers -->
      <template x-for="e in events" :key="e.id">
        <div class="tl-marker"
             :class="[e.kind, e.team_side]"
             :style="`left: ${e.pct}%`"
             @mouseenter="tooltip = e"
             @mouseleave="tooltip = null"
             @click.stop="tooltip = (tooltip && tooltip.id === e.id) ? null : e">
        </div>
      </template>
```

Replace with:
```html
      <!-- Event markers -->
      <template x-for="e in events" :key="e.id">
        <div class="tl-marker"
             :class="[e.kind, e.team_side]"
             :style="`left: ${e.pct}%`"
             @mouseenter="tooltip = e"
             @mouseleave="tooltip = null"
             @click.stop="tooltip = (tooltip && tooltip.id === e.id) ? null : e">
          <span class="tl-marker-label"
                x-text="e.kind === 'goal' ? (e.score || '') : (e.minutes != null ? e.minutes + &quot;'&quot; : '')"></span>
        </div>
      </template>
```

- [ ] **Step 3: Replace single-string tooltip with structured multi-field tooltip**

Find the tooltip div (~line 565):
```html
      <!-- Tooltip -->
      <div x-show="tooltip"
           x-transition.opacity
           class="tl-tooltip"
           :style="`left: clamp(80px, calc(${tooltip ? tooltip.pct : 0}%), calc(100% - 80px))`"
           x-text="tooltip ? tooltip.label : ''">
      </div>
```

Replace with:
```html
      <!-- Tooltip -->
      <div x-show="tooltip"
           x-transition.opacity
           class="tl-tooltip"
           :style="`left: clamp(80px, calc(${tooltip ? tooltip.pct : 0}%), calc(100% - 80px))`"
           style="white-space:normal;max-width:220px;line-height:1.4;padding:.4rem .65rem;">
        <template x-if="tooltip">
          <div>
            <div style="font-weight:700;font-size:.8rem;" x-text="tooltip.label.split('—')[0].trim()"></div>
            <div style="font-size:.75rem;opacity:.85;" x-text="tooltip.label.split('—').slice(1).join('—').trim()"></div>
            <template x-if="tooltip.kind === 'goal' && tooltip.score">
              <div style="font-size:1.1rem;font-weight:700;margin-top:.2rem;" x-text="tooltip.score"></div>
            </template>
            <template x-if="tooltip.kind === 'penalty' && tooltip.minutes != null">
              <div style="font-size:.75rem;opacity:.85;margin-top:.2rem;"
                   x-text="tooltip.minutes + &quot;' &quot; + (tooltip.infraction || '')"></div>
            </template>
          </div>
        </template>
      </div>
```

- [ ] **Step 4: Update mobile CSS — show scrollable bar instead of hiding it**

Find the mobile media query (~line 344):
```css
  @media (max-width: 640px) {
    .tl-bar { display: none; }
    .tl-mobile { display: flex; flex-direction: column; gap: .35rem; }
    ...
  }
  @media (min-width: 641px) { .tl-mobile { display: none; } }
```

Replace only the `@media (max-width: 640px)` block with:
```css
  @media (max-width: 640px) {
    .tl-bar { display: block; overflow-x: auto; -webkit-overflow-scrolling: touch; }
    .tl-track { min-width: 560px; }
    .tl-mobile { display: none; }
  }
  @media (min-width: 641px) { .tl-mobile { display: none; } }
```

Also add `min-width: 560px` to `.tl-track` in the base (non-media) CSS — find it (~line 286) and add `min-width: 560px;`:
```css
  .tl-track {
    position: absolute;
    top: 50%;
    left: 0; right: 0;
    height: 4px;
    background: var(--gray-200);
    border-radius: 2px;
    transform: translateY(-50%);
  }
```
Add `min-width: 560px;` so the track forces width on mobile even without override.

Actually the `min-width` only needs to be on `.tl-bar` for the scroll to work — `overflow-x: auto` on `.tl-bar` with a wide inner content causes scroll. The inner `.tl-track` uses `left:0; right:0` (stretch), so we need a wrapper approach. The simpler fix: set `min-width` on `.tl-bar` inside the mobile media query won't work because it's the outer container. Instead, wrap the inner content with a div that has the min-width.

Simplest approach that doesn't require structural change: in the mobile media query, set `.tl-bar` to `overflow-x: auto` and set `.tl-track, .tl-divider, .tl-marker` to use absolute positioning within a min-width wrapper. The actual working approach:

Replace the `.tl-bar` and add a `.tl-inner` approach. In the mobile media query only:
```css
  @media (max-width: 640px) {
    .tl-bar { display: block; overflow-x: auto; -webkit-overflow-scrolling: touch; height: 56px; }
    .tl-bar > * { min-width: 560px; }
    .tl-mobile { display: none; }
  }
```

The `> *` selector targets `.tl-track` and the `<template>` markers' parent, ensuring minimum width.

Use this final version for the media query:
```css
  @media (max-width: 640px) {
    .tl-bar { display: block; overflow-x: auto; -webkit-overflow-scrolling: touch; }
    .tl-track { min-width: 560px; }
    .tl-mobile { display: none; }
  }
```

And in the base `.tl-bar` (around line 281), add `min-width: 560px;` to `.tl-track` base rule. Actually the `.tl-track` uses `left:0; right:0` which is `position:absolute` stretching — on mobile, the parent `.tl-bar` needs a defined width. The correct approach: make `.tl-bar` have `position: relative; min-width: 560px` on mobile, and the bar itself scrolls inside a wrapper.

The template already has `<div class="tl-wrap">` as the outer wrapper (line 532). Add overflow-x on that:

In the mobile media query, use:
```css
  @media (max-width: 640px) {
    .tl-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
    .tl-bar { min-width: 560px; }
    .tl-mobile { display: none; }
  }
  @media (min-width: 641px) { .tl-mobile { display: none; } }
```

And remove `display: none` from `.tl-bar` in the mobile query (it was the line being replaced).

- [ ] **Step 5: Run all tests**

```bash
cd backend && .venv/bin/pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
cd backend && git add templates/game_detail.html
git commit -m "feat: dot labels, structured tooltip, scrollable mobile timeline"
```
