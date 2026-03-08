# Game Timeline Bar Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a horizontal timeline bar to the game detail page showing goals, penalties, and period boundaries in chronological order.

**Architecture:** A pure Python helper `build_timeline_events()` converts the existing `goals`/`penalties`/`period_markers` data into timeline-ready dicts with `pct` (percentage position), `label`, `kind`, and `team_side`. The result is passed to the Jinja2 template and serialised inline as JSON for an Alpine.js `gameTimeline()` component that handles hover/tap tooltips only — all positioning is server-side CSS.

**Tech Stack:** Python (stats_service.py), Jinja2, Alpine.js (inline script), CSS custom properties for dark/light theme.

---

### Task 1: Build `build_timeline_events()` + tests

**Files:**
- Modify: `backend/app/services/stats_service.py` (add after line ~2397, before `get_game_box_score`)
- Create: `backend/tests/test_game_timeline.py`

**Background**

`get_game_box_score()` already returns:
- `goals` — list of `{period, time, team, player, score, own_goal}` (deduped)
- `penalties` — list of `{period, time, team, player, minutes, infraction}` (deduped)
- `period_markers` — list of `{time, label, period}` (raw period start/end events)
- `home_team`, `away_team` — team name strings

Period mapping for absolute seconds:
```python
_PERIOD_OFFSETS = {1: 0, 2: 1200, 3: 2400, "OT": 3600}
```
Total duration: 3600 s if no OT events; 4200 s if any event is in period "OT" or period > 3.

Time strings are MM:SS (e.g. "14:32"). Parse with:
```python
def _parse_seconds(t: str) -> int:
    parts = t.split(":")
    return int(parts[0]) * 60 + int(parts[1]) if len(parts) == 2 else 0
```

Each timeline event dict must have:
```python
{
    "id":        str,      # unique stable id, e.g. "goal-0", "pen-3"
    "kind":      str,      # "goal" | "penalty"
    "team_side": str,      # "home" | "away" | "unknown"
    "pct":       float,    # 0.0–100.0 percentage along bar
    "label":     str,      # tooltip text, e.g. "GOAL - 14:32 — Team · Player (assist: X)"
}
```

**Step 1: Write the failing tests**

Create `backend/tests/test_game_timeline.py`:

```python
import pytest
from app.services.stats_service import build_timeline_events


def _goals(*args):
    """Helper: list of goal dicts"""
    return list(args)


def _penalties(*args):
    """Helper: list of penalty dicts"""
    return list(args)


def test_empty_game():
    events, total = build_timeline_events([], [], "Home", "Away")
    assert events == []
    assert total == 3600


def test_goal_percentage_period1():
    goals = [{"period": 1, "time": "10:00", "team": "Home", "player": "Smith", "score": "1:0", "own_goal": False}]
    events, total = build_timeline_events(goals, [], "Home", "Away")
    assert total == 3600
    assert len(events) == 1
    ev = events[0]
    assert ev["kind"] == "goal"
    assert ev["team_side"] == "home"
    assert abs(ev["pct"] - (600 / 3600 * 100)) < 0.01
    assert ev["label"].startswith("GOAL - 10:00")
    assert "Home" in ev["label"]
    assert "Smith" in ev["label"]


def test_goal_percentage_period2():
    goals = [{"period": 2, "time": "05:00", "team": "Away", "player": "Jones", "score": "1:1", "own_goal": False}]
    events, total = build_timeline_events(goals, [], "Home", "Away")
    # period 2 starts at 1200s; 5 min = 300s → 1500s
    assert abs(events[0]["pct"] - (1500 / 3600 * 100)) < 0.01
    assert events[0]["team_side"] == "away"


def test_ot_extends_total():
    goals = [{"period": "OT", "time": "03:42", "team": "Home", "player": "Muller", "score": "4:3", "own_goal": False}]
    events, total = build_timeline_events(goals, [], "Home", "Away")
    assert total == 4200
    # OT starts at 3600s; 3:42 = 222s → 3822s
    assert abs(events[0]["pct"] - (3822 / 4200 * 100)) < 0.01


def test_penalty_label():
    pens = [{"period": 1, "time": "08:15", "team": "Away", "player": "Bauer", "minutes": 2, "infraction": "hooking"}]
    events, total = build_timeline_events([], pens, "Home", "Away")
    ev = events[0]
    assert ev["kind"] == "penalty"
    assert ev["label"].startswith("PEN - 08:15")
    assert "Away" in ev["label"]
    assert "Bauer" in ev["label"]
    assert "2 min" in ev["label"]
    assert "hooking" in ev["label"]


def test_unknown_team_side():
    goals = [{"period": 1, "time": "01:00", "team": "Other FC", "player": "X", "score": "1:0", "own_goal": False}]
    events, _ = build_timeline_events(goals, [], "Home", "Away")
    assert events[0]["team_side"] == "unknown"


def test_ids_are_unique():
    goals = [
        {"period": 1, "time": "10:00", "team": "Home", "player": "A", "score": "1:0", "own_goal": False},
        {"period": 2, "time": "05:00", "team": "Away", "player": "B", "score": "1:1", "own_goal": False},
    ]
    pens = [
        {"period": 1, "time": "07:00", "team": "Home", "player": "C", "minutes": 2, "infraction": "tripping"},
    ]
    events, _ = build_timeline_events(goals, pens, "Home", "Away")
    ids = [e["id"] for e in events]
    assert len(ids) == len(set(ids))


def test_events_sorted_by_pct():
    goals = [
        {"period": 3, "time": "01:00", "team": "Home", "player": "A", "score": "3:2", "own_goal": False},
        {"period": 1, "time": "05:00", "team": "Away", "player": "B", "score": "0:1", "own_goal": False},
    ]
    events, _ = build_timeline_events(goals, [], "Home", "Away")
    assert events[0]["pct"] < events[1]["pct"]


def test_missing_time_handled():
    goals = [{"period": 1, "time": "", "team": "Home", "player": "X", "score": "1:0", "own_goal": False}]
    events, _ = build_timeline_events(goals, [], "Home", "Away")
    # Should not crash; pct will be 0
    assert events[0]["pct"] == 0.0


def test_goal_with_assist_in_label():
    # Player string already contains assist info as returned by stats_service: "Smith (Assist: Jones)"
    goals = [{"period": 1, "time": "12:00", "team": "Home", "player": "Smith (Assist: Jones)", "score": "1:0", "own_goal": False}]
    events, _ = build_timeline_events(goals, [], "Home", "Away")
    assert "Smith (Assist: Jones)" in events[0]["label"]
```

**Step 2: Run tests to confirm failure**

```bash
cd backend && .venv/bin/pytest tests/test_game_timeline.py -v 2>&1 | head -30
```
Expected: ImportError or AttributeError — `build_timeline_events` not defined yet.

**Step 3: Implement `build_timeline_events()`**

Add this function to `backend/app/services/stats_service.py` immediately before `get_game_box_score` (around line 2399):

```python
_PERIOD_OFFSETS: dict[int | str, int] = {1: 0, 2: 1200, 3: 2400, "OT": 3600}
_REGULAR_DURATION = 3600   # 60 minutes in seconds
_OT_DURATION      = 4200   # 70 minutes in seconds (10-min OT)


def _parse_time_seconds(time_str: str) -> int:
    """Parse 'MM:SS' into total seconds. Returns 0 on bad input."""
    parts = (time_str or "").split(":")
    if len(parts) == 2:
        try:
            return int(parts[0]) * 60 + int(parts[1])
        except ValueError:
            pass
    return 0


def build_timeline_events(
    goals: list[dict],
    penalties: list[dict],
    home_name: str,
    away_name: str,
) -> tuple[list[dict], int]:
    """
    Convert goals/penalties into timeline event dicts with percentage positions.

    Returns (events, total_seconds) where:
      - events is sorted by pct ascending
      - total_seconds is 3600 (regular) or 4200 (OT present)
    """
    has_ot = any(
        str(g.get("period", "")).upper() == "OT" or (isinstance(g.get("period"), int) and g["period"] > 3)
        for g in goals
    ) or any(
        str(p.get("period", "")).upper() == "OT" or (isinstance(p.get("period"), int) and p["period"] > 3)
        for p in penalties
    )
    total_seconds = _OT_DURATION if has_ot else _REGULAR_DURATION

    def _period_key(period) -> int | str:
        if isinstance(period, str) and period.upper() == "OT":
            return "OT"
        try:
            p = int(period)
            return "OT" if p > 3 else p
        except (TypeError, ValueError):
            return 1

    def _abs_seconds(period, time_str: str) -> int:
        key = _period_key(period)
        offset = _PERIOD_OFFSETS.get(key, 0)
        return offset + _parse_time_seconds(time_str)

    def _team_side(team_label: str) -> str:
        if team_label == home_name:
            return "home"
        if team_label == away_name:
            return "away"
        return "unknown"

    events: list[dict] = []

    for i, g in enumerate(goals):
        abs_s = _abs_seconds(g.get("period"), g.get("time", ""))
        pct = abs_s / total_seconds * 100
        team = g.get("team", "")
        player = g.get("player", "") or ""
        label = f"GOAL - {g.get('time', '')} — {team}"
        if player:
            label += f" · {player}"
        events.append({
            "id":        f"goal-{i}",
            "kind":      "goal",
            "team_side": _team_side(team),
            "pct":       round(pct, 4),
            "label":     label,
        })

    for i, p in enumerate(penalties):
        abs_s = _abs_seconds(p.get("period"), p.get("time", ""))
        pct = abs_s / total_seconds * 100
        team = p.get("team", "")
        player = p.get("player", "") or ""
        minutes = p.get("minutes", 0)
        infraction = p.get("infraction", "") or ""
        label = f"PEN - {p.get('time', '')} — {team}"
        if player:
            label += f" · {player}"
        label += f" ({minutes} min, {infraction})" if infraction else f" ({minutes} min)"
        events.append({
            "id":        f"pen-{i}",
            "kind":      "penalty",
            "team_side": _team_side(team),
            "pct":       round(pct, 4),
            "label":     label,
        })

    events.sort(key=lambda e: e["pct"])
    return events, total_seconds
```

**Step 4: Run tests to confirm they pass**

```bash
cd backend && .venv/bin/pytest tests/test_game_timeline.py -v
```
Expected: 10 passed.

**Step 5: Commit**

```bash
git add backend/app/services/stats_service.py backend/tests/test_game_timeline.py
git commit -m "feat: add build_timeline_events() helper for game timeline bar"
```

---

### Task 2: Wire timeline data into `get_game_box_score()` + route

**Files:**
- Modify: `backend/app/services/stats_service.py` (return dict at line ~2889)
- No changes to `main.py` needed (route passes `box` dict directly to template)

**Step 1: Write a failing test**

Add to `backend/tests/test_game_timeline.py`:

```python
from app.services.stats_service import get_game_box_score
from app.services.database import DatabaseService
from sqlalchemy import text


def _make_db_with_finished_game():
    svc = DatabaseService("sqlite:///:memory:")
    svc.initialize()
    with svc.session_scope() as session:
        session.execute(text("INSERT INTO seasons (id) VALUES (2025)"))
        session.execute(text("INSERT INTO clubs (id, season_id) VALUES (1, 2025)"))
        session.execute(text("INSERT INTO teams (id, season_id, club_id, name) VALUES (1, 2025, 1, 'Home FC')"))
        session.execute(text("INSERT INTO teams (id, season_id, club_id, name) VALUES (2, 2025, 1, 'Away FC')"))
        session.execute(text("""
            INSERT INTO games (id, season_id, home_team_id, away_team_id, home_score, away_score, status)
            VALUES (999, 2025, 1, 2, 2, 1, 'finished')
        """))
        session.execute(text("""
            INSERT INTO game_events (game_id, event_type, period, time)
            VALUES (999, 'Torschütze 1:0 Meier', 1, '10:00')
        """))
    return svc


def test_box_score_includes_timeline_events(monkeypatch):
    svc = _make_db_with_finished_game()
    import app.services.database as db_module
    monkeypatch.setattr(db_module, "_db_service", svc)
    box = get_game_box_score(999)
    assert "timeline_events" in box
    assert "total_seconds" in box
    assert isinstance(box["timeline_events"], list)
    assert box["total_seconds"] in (3600, 4200)
```

Run to confirm failure:
```bash
cd backend && .venv/bin/pytest tests/test_game_timeline.py::test_box_score_includes_timeline_events -v
```
Expected: FAIL — KeyError `timeline_events`.

**Step 2: Add to return dict in `get_game_box_score()`**

In `backend/app/services/stats_service.py`, inside the `return { ... }` block at line ~2889, add two keys after `"best_players"`:

```python
            "timeline_events":   _timeline_events,
            "total_seconds":     _total_seconds,
```

And just before the `return`, compute them by adding these two lines immediately above the `return`:

```python
        _timeline_events, _total_seconds = build_timeline_events(
            goals, penalties, home_name, away_name
        )
```

**Step 3: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_game_timeline.py -v
```
Expected: 11 passed.

**Step 4: Commit**

```bash
git add backend/app/services/stats_service.py backend/tests/test_game_timeline.py
git commit -m "feat: include timeline_events in get_game_box_score return dict"
```

---

### Task 3: Add CSS, HTML, and Alpine.js to `game_detail.html`

**Files:**
- Modify: `backend/templates/game_detail.html`

The timeline is inserted between the scorebox closing `</div>` (line 416) and the `<!-- Tabs -->` comment (line 422).

**Step 1: Add CSS**

Inside the `<style>` block (before line 255 `</style>`), add:

```css
  /* ── Game Timeline ──────────────────────────────────────────────────────── */
  .tl-wrap {
    background: var(--card-bg, white);
    border: 1px solid var(--gray-200);
    border-radius: 8px;
    padding: 1rem 1.25rem 1.25rem;
    margin-bottom: 1rem;
  }
  .tl-heading {
    font-size: .65rem;
    text-transform: uppercase;
    letter-spacing: .06em;
    color: var(--gray-400);
    margin-bottom: .75rem;
  }
  /* ── Desktop horizontal bar ── */
  .tl-bar {
    position: relative;
    height: 48px;          /* goals above (24px) + track (4px) + penalties below (20px) */
    margin: 0 4px;
  }
  .tl-track {
    position: absolute;
    top: 50%;
    left: 0; right: 0;
    height: 4px;
    background: var(--gray-200);
    border-radius: 2px;
    transform: translateY(-50%);
  }
  /* Period dividers */
  .tl-divider {
    position: absolute;
    top: 0; bottom: 0;
    width: 1px;
    background: var(--gray-300);
  }
  .tl-period-label {
    position: absolute;
    bottom: -1.2rem;
    transform: translateX(-50%);
    font-size: .6rem;
    color: var(--gray-400);
    white-space: nowrap;
    pointer-events: none;
  }
  /* Markers */
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
  .tl-marker:hover { transform: translateX(-50%) scale(1.4); }
  .tl-marker.goal { top: calc(50% - 14px); }
  .tl-marker.penalty {
    top: calc(50% + 6px);
    border-radius: 2px;   /* square tick for penalties */
    width: 8px; height: 8px;
  }
  .tl-marker.home { background: #3b82f6; }          /* blue — works in light + dark */
  .tl-marker.away { background: #f59e0b; }          /* amber — works in light + dark */
  .tl-marker.unknown { background: var(--gray-400); }
  /* Tooltip */
  .tl-tooltip {
    position: absolute;
    top: -2.6rem;
    background: var(--swiss-dark, #1a1a1a);
    color: #fff;
    font-size: .72rem;
    padding: .25rem .55rem;
    border-radius: 4px;
    white-space: nowrap;
    pointer-events: none;
    z-index: 10;
    transform: translateX(-50%);
  }
  html.dark-mode .tl-tooltip {
    background: var(--gray-700);
  }
  /* ── Mobile vertical layout ── */
  @media (max-width: 640px) {
    .tl-bar { display: none; }
    .tl-mobile { display: flex; flex-direction: column; gap: .35rem; }
    .tl-mobile-row {
      display: flex;
      align-items: center;
      gap: .5rem;
      font-size: .75rem;
    }
    .tl-mobile-dot {
      width: 8px; height: 8px;
      border-radius: 50%;
      flex-shrink: 0;
    }
    .tl-mobile-dot.penalty { border-radius: 2px; }
    .tl-mobile-dot.home { background: #3b82f6; }
    .tl-mobile-dot.away { background: #f59e0b; }
    .tl-mobile-dot.unknown { background: var(--gray-400); }
    .tl-mobile-label { color: var(--gray-700); line-height: 1.3; }
    .tl-mobile-divider {
      border-top: 1px solid var(--gray-200);
      margin: .15rem 0;
      font-size: .6rem;
      color: var(--gray-400);
      text-align: center;
      padding-top: .15rem;
    }
  }
  @media (min-width: 641px) {
    .tl-mobile { display: none; }
  }
```

**Step 2: Add HTML**

Insert between line 416 (`  </div>` closing the scorebox) and line 418 (`  {% if playoff_series %}`):

```html

  {% if game.timeline_events %}
  <div class="tl-wrap"
       x-data="gameTimeline({{ game.timeline_events | tojson }}, {{ game.total_seconds }})"
       @click.outside="tooltip = null">
    <div class="tl-heading">Timeline</div>

    <!-- Desktop horizontal bar -->
    <div class="tl-bar">
      <div class="tl-track"></div>

      <!-- Period dividers -->
      {% if game.total_seconds == 4200 %}
        {% set dividers = [(1200/4200*100, 'P1'), (2400/4200*100, 'P2'), (3600/4200*100, 'P3'), (4200/4200*100, 'OT')] %}
      {% else %}
        {% set dividers = [(1200/3600*100, 'P1'), (2400/3600*100, 'P2'), (3600/3600*100, 'P3')] %}
      {% endif %}
      {% for pct, lbl in dividers %}
      <div class="tl-divider" style="left:{{ '%.2f'|format(pct) }}%">
        <span class="tl-period-label">{{ lbl }}</span>
      </div>
      {% endfor %}

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

      <!-- Tooltip -->
      <div x-show="tooltip"
           x-transition.opacity
           class="tl-tooltip"
           :style="`left: clamp(60px, calc(${tooltip ? tooltip.pct : 0}% ), calc(100% - 60px))`"
           x-text="tooltip ? tooltip.label : ''">
      </div>
    </div>

    <!-- Mobile vertical list -->
    <div class="tl-mobile">
      {% set ns = namespace(last_period=none) %}
      {% for e in game.timeline_events %}
        {% set cur_period = e.id.split('-')[0] %}
        {# Insert period divider when period changes — use pct ranges as proxy #}
      <div class="tl-mobile-row">
        <div class="tl-mobile-dot {{ e.kind }} {{ e.team_side }}"></div>
        <div class="tl-mobile-label">{{ e.label }}</div>
      </div>
      {% endfor %}
    </div>
  </div>
  {% endif %}
```

**Step 3: Add Alpine.js component function**

In the existing `<script>` block (line 257), add `gameTimeline` after the last existing function (before the closing `</script>`):

```javascript
function gameTimeline(events, totalSeconds) {
  return {
    events,
    totalSeconds,
    tooltip: null,
  };
}
```

**Step 4: Smoke-test manually**

Start the dev server and open a finished game detail page that has events:

```bash
cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000
```

- Navigate to a finished game (e.g. `/de/game/12345`)
- Verify the timeline bar appears between scorebox and tabs
- Hover a marker — tooltip should appear
- Click a marker — tooltip toggles
- Toggle dark mode — colors and tooltip background should adapt
- Resize to mobile width — horizontal bar disappears, vertical list appears

**Step 5: Run full test suite**

```bash
cd backend && .venv/bin/pytest -v 2>&1 | tail -20
```
Expected: all existing tests pass + 11 new timeline tests pass.

**Step 6: Commit**

```bash
git add backend/templates/game_detail.html
git commit -m "feat: add game timeline bar to game detail page"
```
