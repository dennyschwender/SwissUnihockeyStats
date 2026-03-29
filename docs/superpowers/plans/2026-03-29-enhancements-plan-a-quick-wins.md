# Enhancements Plan A — Quick Wins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add PPG column to team roster and group playoff/playout series by round in league standings.

**Architecture:** Two independent changes — (1) add a computed field to existing roster dicts and expose it in the template; (2) extract a shared series-building helper in `stats_service.py`, replace the duplicate code in `main.py` with a call to it, and update the Alpine template to iterate a nested `[{phase_name, series_list}]` structure instead of a flat list.

**Tech Stack:** Python/SQLAlchemy (stats_service, main), Jinja2 + Alpine.js (templates), pytest

---

## File Map

| File | Change |
|---|---|
| `backend/app/services/stats_service.py` | Add `ppg` to three `roster.append()` blocks; add `_build_series_rounds()` helper |
| `backend/app/main.py` | Replace inline series-building loop with `_build_series_rounds()` call |
| `backend/templates/team_detail.html` | Add PPG column header, cell, and no-op sort (numeric, already handled) |
| `backend/templates/league_detail.html` | Wrap series loop in outer round loop; add round header |
| `backend/tests/test_stats_service.py` | Tests for `ppg` in roster + `_build_series_rounds()` grouping |

---

## Task 1: PPG in team roster service

**Files:**
- Modify: `backend/app/services/stats_service.py` (lines ~1750–1837)
- Test: `backend/tests/test_stats_service.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_stats_service.py` inside a new `class TestTeamRosterPPG`:

```python
class TestTeamRosterPPG:
    """Test that roster player dicts include ppg field."""

    def test_ppg_present_in_roster_dicts(self):
        from app.services.database import get_database_service
        from app.models.db_models import (
            Team, Season, Player, TeamPlayer, PlayerStatistics
        )
        db = get_database_service()
        with db.session_scope() as session:
            season = session.query(Season).first()
            if not season:
                pytest.skip("No season in DB")
            team = session.query(Team).filter(Team.season_id == season.id).first()
            if not team:
                pytest.skip("No team in DB")

        result = get_team_detail(team_id=team.id, season_id=season.id)
        roster = result.get("roster", [])
        if not roster:
            pytest.skip("No roster players")
        for p in roster:
            assert "ppg" in p, f"ppg key missing from player dict: {p}"

    def test_ppg_is_none_when_gp_is_zero(self):
        from app.services.stats_service import _compute_ppg
        assert _compute_ppg(10, 0) is None
        assert _compute_ppg(0, 0) is None

    def test_ppg_rounded_to_two_decimals(self):
        from app.services.stats_service import _compute_ppg
        result = _compute_ppg(10, 3)
        assert result == 3.33
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && .venv/bin/pytest tests/test_stats_service.py::TestTeamRosterPPG -v
```

Expected: FAIL — `ppg key missing from player dict` or `KeyError`.

- [ ] **Step 3: Add ppg to the three roster.append() blocks in stats_service.py**

There are three `roster.append({...})` calls in `get_team_detail` (around lines 1750, 1800, 1823). Add `"ppg"` to each one. The pattern is: `round(pts_val / gp_val, 2) if gp_val else None`.

**Block 1** (official roster path, ~line 1750):
```python
roster.append(
    {
        "player_id": pl.person_id,
        "name": pl.full_name or f"Player {pl.person_id}",
        "number": number,
        "position": position,
        "gp": gp_val,
        "g": g_val,
        "a": a_val,
        "pts": pts_val,
        "pim": pim_val,
        "ppg": round(pts_val / gp_val, 2) if gp_val else None,
    }
)
```

**Block 2** (extras from game lineups, ~line 1800):
```python
roster.append(
    {
        "player_id": pid,
        "name": info["name"],
        "number": info["number"],
        "position": _POS_ABBREV.get(
            (info["position"] or "").lower(), info["position"] or ""
        ),
        "gp": ps.get("gp") or info["gp"],
        "g": g_val,
        "a": a_val,
        "pts": pts_val,
        "pim": pim_val,
        "from_games": True,
        "ppg": round(pts_val / (ps.get("gp") or info["gp"]), 2) if (ps.get("gp") or info["gp"]) else None,
    }
)
```

**Block 3** (game-only roster, ~line 1823):
```python
roster.append(
    {
        "player_id": pid,
        "name": info["name"],
        "number": info["number"],
        "position": _POS_ABBREV.get(
            (info["position"] or "").lower(), info["position"] or ""
        ),
        "gp": info["gp"],
        "g": info["g"],
        "a": info["a"],
        "pts": info["pts"],
        "pim": info["pim"],
        "ppg": round(info["pts"] / info["gp"], 2) if info["gp"] else None,
    }
)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && .venv/bin/pytest tests/test_stats_service.py::TestTeamRosterPPG -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/services/stats_service.py tests/test_stats_service.py
git commit -m "feat: add ppg field to team roster player dicts"
```

---

## Task 2: PPG column in team_detail.html

**Files:**
- Modify: `backend/templates/team_detail.html` (lines ~197–214)

- [ ] **Step 1: Add PPG column header after PTS header**

Find the `PIM` header line (~line 198):
```html
<th style="{{ th_ctr }}"><button @click="sort('pim')" style="{{ btn }}">PIM<span style="font-size:.7rem;opacity:.55;" x-text="icon('pim')"></span></button></th>
```

Insert before it (after the PTS `</th>`):
```html
<th style="{{ th_ctr }}"><button @click="sort('ppg')" style="{{ btn }}">PPG<span style="font-size:.7rem;opacity:.55;" x-text="icon('ppg')"></span></button></th>
```

- [ ] **Step 2: Add PPG cell after PTS cell**

Find the PIM cell (~line 214):
```html
<td style="padding:.6rem .5rem;text-align:center;" x-text="p.pim"></td>
```

Insert before it (after the PTS `</td>`):
```html
<td style="padding:.6rem .5rem;text-align:center;color:var(--gray-500);" x-text="p.ppg != null ? p.ppg : '—'"></td>
```

- [ ] **Step 3: Verify in browser (or run template test)**

```bash
cd backend && .venv/bin/pytest tests/ -k "team" -v
```

Expected: all existing team tests PASS, no new failures.

- [ ] **Step 4: Commit**

```bash
cd backend && git add templates/team_detail.html
git commit -m "feat: add PPG column to team roster table"
```

---

## Task 3: _build_series_rounds helper in stats_service.py

**Files:**
- Modify: `backend/app/services/stats_service.py` (add helper before `get_playoff_series_for_game`)
- Test: `backend/tests/test_stats_service.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_stats_service.py`:

```python
class TestBuildSeriesRounds:
    """Test _build_series_rounds returns grouped phase structure."""

    def test_returns_list_of_phase_dicts(self):
        from app.services.stats_service import _build_series_rounds
        from app.services.database import get_database_service
        from app.models.db_models import LeagueGroup
        db = get_database_service()
        with db.session_scope() as session:
            # Use any existing playoff group IDs
            groups = session.query(LeagueGroup).limit(2).all()
            if not groups:
                pytest.skip("No LeagueGroup rows in DB")
            group_ids = [g.id for g in groups]
            season_id = groups[0].league.season_id if groups[0].league else 2025
            result = _build_series_rounds(group_ids, season_id, session)
        assert isinstance(result, list)
        for phase in result:
            assert "phase_name" in phase
            assert "series_list" in phase
            assert isinstance(phase["series_list"], list)

    def test_empty_group_ids_returns_empty_list(self):
        from app.services.stats_service import _build_series_rounds
        from app.services.database import get_database_service
        db = get_database_service()
        with db.session_scope() as session:
            result = _build_series_rounds([], 2025, session)
        assert result == []

    def test_series_have_required_keys(self):
        from app.services.stats_service import _build_series_rounds
        from app.services.database import get_database_service
        from app.models.db_models import LeagueGroup, Game
        db = get_database_service()
        with db.session_scope() as session:
            # Find a group that has games
            grp = (
                session.query(LeagueGroup)
                .join(Game, Game.group_id == LeagueGroup.id)
                .first()
            )
            if not grp:
                pytest.skip("No LeagueGroup with games")
            result = _build_series_rounds([grp.id], grp.league.season_id if grp.league else 2025, session)
        if not result or not result[0]["series_list"]:
            pytest.skip("No series in result")
        s = result[0]["series_list"][0]
        for key in ("team_a_id", "team_b_id", "team_a_name", "team_b_name",
                    "team_a_wins", "team_b_wins", "games"):
            assert key in s, f"Missing key {key} in series dict"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && .venv/bin/pytest tests/test_stats_service.py::TestBuildSeriesRounds -v
```

Expected: FAIL — `ImportError: cannot import name '_build_series_rounds'`.

- [ ] **Step 3: Add _build_series_rounds to stats_service.py**

Insert this function immediately before `get_playoff_series_for_game` (around line 3669):

```python
def _build_series_rounds(
    phase_group_ids: list[int],
    season_id: int,
    session,
    reg_rank: Optional[dict] = None,
) -> list[dict]:
    """Return [{phase_name, series_list}] grouped by LeagueGroup (one per round).

    Args:
        phase_group_ids: LeagueGroup.id values for one canonical phase (playoff or playout).
        season_id: season to filter games by.
        session: active SQLAlchemy session.
        reg_rank: optional dict[team_id → int rank] from regular season standings.

    Returns list of phase dicts ordered by earliest game date ascending.
    """
    if not phase_group_ids:
        return []

    phase_groups = (
        session.query(LeagueGroup)
        .filter(LeagueGroup.id.in_(phase_group_ids))
        .all()
    )
    group_by_id = {g.id: g for g in phase_groups}

    phase_games = (
        session.query(Game)
        .filter(
            Game.group_id.in_(phase_group_ids),
            Game.season_id == season_id,
        )
        .order_by(Game.game_date.asc())
        .all()
    )
    if not phase_games:
        return []

    all_team_ids = {g.home_team_id for g in phase_games} | {g.away_team_id for g in phase_games}
    _snm: dict[int, str] = {}
    _slogo: dict[int, Optional[str]] = {}
    for _t in (
        session.query(Team)
        .filter(Team.id.in_(all_team_ids), Team.season_id == season_id)
        .all()
    ):
        _snm[_t.id] = _t.name or _t.text or f"Team {_t.id}"
        if _t.logo_url:
            _slogo[_t.id] = _t.logo_url
    _missing = all_team_ids - _snm.keys()
    if _missing:
        for _t in (
            session.query(Team)
            .filter(Team.id.in_(_missing), Team.name.isnot(None))
            .all()
        ):
            _snm.setdefault(_t.id, _t.name)
            if _t.logo_url:
                _slogo.setdefault(_t.id, _t.logo_url)

    # Bucket games by group_id → sorted team-pair key
    _pairs_by_group: dict[int, dict[tuple, list]] = {g.id: {} for g in phase_groups}
    for _g in phase_games:
        _key = tuple(sorted([_g.home_team_id, _g.away_team_id]))
        _pairs_by_group[_g.group_id].setdefault(_key, []).append(_g)

    def _earliest(gid: int) -> datetime:
        dates = [g.game_date for g in phase_games if g.group_id == gid and g.game_date]
        return min(dates) if dates else datetime.max

    ordered_groups = sorted(
        [g for g in phase_groups if _pairs_by_group.get(g.id)],
        key=lambda g: _earliest(g.id),
    )

    phases: list[dict] = []
    for _grp in ordered_groups:
        group_series: list[dict] = []
        for _key, _pgames in sorted(
            _pairs_by_group[_grp.id].items(),
            key=lambda x: _snm.get(x[0][0] if isinstance(x[0], tuple) else x[0], ""),
        ):
            _sorted = sorted(_pgames, key=lambda x: x.game_date or datetime.min)
            _first_g = _sorted[0]
            _ta = _first_g.home_team_id
            _tb = _first_g.away_team_id
            _ta_wins = _tb_wins = 0
            _games_list: list[dict] = []
            for _g in _sorted:
                _played = _g.home_score is not None
                if _played:
                    _home_wins = _g.home_score > _g.away_score
                    if _g.home_team_id == _ta:
                        if _home_wins:
                            _ta_wins += 1
                        else:
                            _tb_wins += 1
                    else:
                        if _home_wins:
                            _tb_wins += 1
                        else:
                            _ta_wins += 1
                _games_list.append(
                    {
                        "game_id": _g.id,
                        "date": _g.game_date.strftime("%d.%m.%Y") if _g.game_date else "",
                        "weekday": _g.game_date.strftime("%a") if _g.game_date else "",
                        "home_team": _snm.get(_g.home_team_id, f"Team {_g.home_team_id}"),
                        "away_team": _snm.get(_g.away_team_id, f"Team {_g.away_team_id}"),
                        "home_team_id": _g.home_team_id,
                        "away_team_id": _g.away_team_id,
                        "home_score": _g.home_score,
                        "away_score": _g.away_score,
                        "played": _played,
                    }
                )
            group_series.append(
                {
                    "team_a_id": _ta,
                    "team_b_id": _tb,
                    "team_a_name": _snm.get(_ta, f"Team {_ta}"),
                    "team_b_name": _snm.get(_tb, f"Team {_tb}"),
                    "team_a_logo": _slogo.get(_ta),
                    "team_b_logo": _slogo.get(_tb),
                    "team_a_rank": (reg_rank or {}).get(_ta),
                    "team_b_rank": (reg_rank or {}).get(_tb),
                    "team_a_wins": _ta_wins,
                    "team_b_wins": _tb_wins,
                    "games": _games_list,
                }
            )
        phases.append(
            {
                "phase_name": _grp.phase or "",
                "series_list": group_series,
            }
        )
    return phases
```

Note: `LeagueGroup`, `Game`, `Team` are already imported at the top of `stats_service.py`. `Optional` and `datetime` are also already imported.

- [ ] **Step 4: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_stats_service.py::TestBuildSeriesRounds -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/services/stats_service.py tests/test_stats_service.py
git commit -m "feat: add _build_series_rounds helper to stats_service"
```

---

## Task 4: Use _build_series_rounds in main.py

**Files:**
- Modify: `backend/app/main.py` (lines ~3346–3447)

The current block opens a new `db.session_scope()` per phase and builds the flat `_series_list`. Replace it entirely.

- [ ] **Step 1: Replace the series-building loop in main.py**

Find the block (around line 3346):
```python
    # --- Series data per phase (playoff / playout) ---
    from datetime import date as _date
    from app.models.db_models import Team as _TmModel

    # Build regular-season rank map: team_id → rank (1-based position in standings)
    _reg_rank: dict[int, int] = {}
    for _ri, _rs in enumerate(standings, 1):
        _tid = _rs.get("team_id")
        if _tid:
            _reg_rank[_tid] = _ri
    series_by_phase: dict[str, list[dict]] = {}
    for _sph, _sgids in _phase_to_group_ids.items():
        if _sph not in ("playoff", "playout"):
            continue
        with db.session_scope() as _ssess:
            ... (long block ending at line 3447)
            series_by_phase[_sph] = _series_list
```

Replace the entire block from `# --- Series data per phase` to `series_by_phase[_sph] = _series_list` (inclusive) with:

```python
    # --- Series data per phase (playoff / playout) ---
    from app.services.stats_service import _build_series_rounds

    # Build regular-season rank map: team_id → rank (1-based position in standings)
    _reg_rank: dict[int, int] = {}
    for _ri, _rs in enumerate(standings, 1):
        _tid = _rs.get("team_id")
        if _tid:
            _reg_rank[_tid] = _ri

    series_by_phase: dict[str, list[dict]] = {}
    for _sph, _sgids in _phase_to_group_ids.items():
        if _sph not in ("playoff", "playout"):
            continue
        with db.session_scope() as _ssess:
            series_by_phase[_sph] = _build_series_rounds(
                _sgids, league_data["season_id"], _ssess, _reg_rank
            )
```

- [ ] **Step 2: Run existing tests to verify nothing broke**

```bash
cd backend && .venv/bin/pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all previously passing tests still PASS.

- [ ] **Step 3: Commit**

```bash
cd backend && git add app/main.py
git commit -m "refactor: use _build_series_rounds helper in league detail route"
```

---

## Task 5: Update league_detail.html for nested round structure

**Files:**
- Modify: `backend/templates/league_detail.html`

The `shownSeries` getter now returns `[{phase_name, series_list}, ...]` instead of `[{team_a_id, ...}]`. Update the Alpine data and template accordingly.

- [ ] **Step 1: Add hasAnySeries computed getter to Alpine data block**

Find the `get shownSeries()` getter (~line 83):
```javascript
    get shownSeries() {
      const ph = Alpine.store('leagueFilter').phase;
      if (ph === 'playoff' || ph === 'playout') return _seriesByPhase[ph] || [];
      return [];
    },
```

Leave `shownSeries` unchanged (still returns the phases array from `_seriesByPhase`). Add a new getter immediately after it:

```javascript
    get hasAnySeries() {
      return this.shownSeries.some(r => r.series_list && r.series_list.length > 0);
    },
```

- [ ] **Step 2: Replace the bracket template in league_detail.html**

Find the bracket section (around line 241):
```html
      <!-- Playoff / Playout: series bracket view -->
      <template x-if="isSeriesPhase">
        <div style="...">
          <template x-if="shownSeries.length === 0">
            ...empty state...
          </template>
          <template x-for="s in shownSeries" :key="s.team_a_id + '-' + s.team_b_id">
            ...series card...
          </template>
        </div>
      </template>
```

Replace the entire `<template x-if="isSeriesPhase">` block with:

```html
      <!-- Playoff / Playout: series bracket view grouped by round -->
      <template x-if="isSeriesPhase">
        <div>
          <template x-if="!hasAnySeries">
            <div style="text-align:center;padding:3rem;color:var(--gray-500);">
              <p style="font-size:2rem">🏆</p>
              <p>No series data available yet.</p>
            </div>
          </template>
          <template x-for="round in shownSeries" :key="round.phase_name">
            <div>
              <template x-if="round.phase_name && round.series_list.length > 0">
                <h3 style="font-size:.85rem;font-weight:700;color:var(--gray-500);text-transform:uppercase;letter-spacing:.05em;margin:1.25rem 0 .5rem;" x-text="round.phase_name"></h3>
              </template>
              <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:1rem;align-items:start;">
                <template x-for="s in round.series_list" :key="s.team_a_id + '-' + s.team_b_id">
                  <div style="background:var(--white);border:1px solid var(--gray-200);border-radius:.75rem;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.06);">
                    <!-- Series header -->
                    <div style="background:var(--gray-50);padding:.75rem 1rem;border-bottom:1px solid var(--gray-200);">
                      <div style="display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:.5rem;">
                        <!-- Team A (left-aligned) -->
                        <a :href="'/{{ locale }}/team/' + s.team_a_id"
                           style="display:flex;align-items:center;gap:.4rem;font-weight:600;font-size:.95rem;color:var(--gray-900);text-decoration:none;min-width:0;">
                          <template x-if="s.team_a_logo">
                            <img :src="s.team_a_logo" :alt="s.team_a_name" style="width:1.5rem;height:1.5rem;object-fit:contain;flex-shrink:0;">
                          </template>
                          <span style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                            <template x-if="s.team_a_rank"><span x-text="s.team_a_rank + '. '" style="color:var(--gray-400);font-weight:400;"></span></template><span x-text="s.team_a_name"></span>
                          </span>
                        </a>
                        <!-- Series score (centered) -->
                        <div style="display:flex;align-items:center;gap:.35rem;font-size:1.1rem;font-weight:700;color:var(--gray-700);white-space:nowrap;">
                          <span x-text="s.team_a_wins"></span>
                          <span style="color:var(--gray-400);font-size:.9rem;">–</span>
                          <span x-text="s.team_b_wins"></span>
                        </div>
                        <!-- Team B (right-aligned) -->
                        <a :href="'/{{ locale }}/team/' + s.team_b_id"
                           style="display:flex;align-items:center;justify-content:flex-end;gap:.4rem;font-weight:600;font-size:.95rem;color:var(--gray-900);text-decoration:none;min-width:0;">
                          <span style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-align:right;">
                            <span x-text="s.team_b_name"></span><template x-if="s.team_b_rank"><span x-text="' ' + s.team_b_rank + '.'" style="color:var(--gray-400);font-weight:400;"></span></template>
                          </span>
                          <template x-if="s.team_b_logo">
                            <img :src="s.team_b_logo" :alt="s.team_b_name" style="width:1.5rem;height:1.5rem;object-fit:contain;flex-shrink:0;">
                          </template>
                        </a>
                      </div>
                    </div>
                    <!-- Individual game results -->
                    <div style="padding:.5rem 0;">
                      <template x-for="(g, idx) in s.games" :key="g.game_id">
                        <div @click="g.game_id && (window.location='/{{ locale }}/game/' + g.game_id)"
                             :style="'display:flex;align-items:center;justify-content:space-between;padding:.4rem 1rem;cursor:' + (g.game_id ? 'pointer' : 'default') + ';'"
                             onmouseover="this.style.background='var(--gray-50)'" onmouseout="this.style.background=''">
                          <div style="display:flex;align-items:center;gap:.6rem;min-width:0;flex:1;">
                            <span style="font-size:.75rem;color:var(--gray-400);white-space:nowrap;" x-text="g.weekday + ' ' + g.date"></span>
                            <span style="font-size:.85rem;font-weight:500;color:var(--gray-700);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" x-text="g.home_team + ' – ' + g.away_team"></span>
                          </div>
                          <div style="white-space:nowrap;margin-left:.75rem;">
                            <template x-if="g.played">
                              <span style="font-size:.9rem;font-weight:700;color:var(--gray-900);"
                                    x-text="g.home_score + ':' + g.away_score"></span>
                            </template>
                            <template x-if="!g.played">
                              <span style="font-size:.75rem;color:var(--gray-400);font-style:italic;">upcoming</span>
                            </template>
                          </div>
                        </div>
                      </template>
                    </div>
                  </div>
                </template>
              </div>
            </div>
          </template>
        </div>
      </template>
```

- [ ] **Step 3: Run all tests**

```bash
cd backend && .venv/bin/pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
cd backend && git add templates/league_detail.html
git commit -m "feat: group playoff/playout series by round in league standings"
```
