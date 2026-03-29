# Enhancements Spec A — Quick Wins

## Overview

Two small, independent UI enhancements requiring minimal backend changes:
- Roster PPG column in team detail
- Playoff/playout bracket grouped by round in league detail standings

---

## Enhancement 1: Roster PPG Column (team detail)

### Problem
The team detail roster tab shows GP, G, A, PTS, PIM but not PPG (points per game). Players are ranked by PTS but there's no per-game rate column.

### Design

**Backend (`backend/app/services/stats_service.py`):**

In `get_team_detail`, find where each player dict is built for `team.roster`. Add:
```python
"ppg": round(p_pts / p_gp, 2) if p_gp else None,
```
(where `p_pts` and `p_gp` are the player's existing points and games_played values)

**Template (`backend/templates/team_detail.html`):**

In the roster Alpine component:
1. Add `ppg` to the sort function (numeric, same pattern as existing columns)
2. Add column header button: `PPG` with sort arrow, after PTS header
3. Add cell: `x-text="p.ppg != null ? p.ppg : '—'"`, after PTS cell

**i18n:** No new keys needed — PPG is a universal abbreviation already used on player_detail.

**Tests:** Add assertion that `get_team_detail` roster player dicts include `ppg` key.

---

## Enhancement 2: League Standings Playoff/Playout Grouped by Round

### Problem
The league detail standings tab shows playoff/playout series as a flat list with no round groupings. Game detail shows the same data grouped by round (Quarterfinals → Semifinals → Final) with round headers. The league detail should match.

### Design

**Root cause:** `series_by_phase` in the league detail route builds `{"playoff": [flat list], "playout": [flat list]}`. The `get_playoff_series_for_game` function already groups by round but is game-scoped. The league detail needs the same round-grouping applied at league scope.

**Backend (`backend/app/services/stats_service.py`):**

Extract a shared helper `_build_series_rounds(phase_group_ids, season_id, session)` from `get_playoff_series_for_game` that returns `[{"phase_name": str, "series_list": [...]}]` — the same `phases` structure already used in game_detail.

Update the league_detail route's `series_by_phase` building logic (in `main.py` around line 3447) to call this helper, producing:
```python
series_by_phase = {
    "playoff": [{"phase_name": "Quarterfinals", "series_list": [...]}, ...],
    "playout": [{"phase_name": "Playouts", "series_list": [...]}],
}
```

**Template (`backend/templates/league_detail.html`):**

The current playoff bracket template iterates `x-for="s in shownSeries"` (flat). Replace with nested iteration:
1. `x-for="round in shownSeries"` (where `shownSeries` now returns the phases list)
2. Inside each round: render round header (`round.phase_name`) + `x-for="s in round.series_list"`

The series card HTML stays identical to the existing card — only the outer loop structure changes.

`shownSeries` computed property in Alpine: currently returns `_seriesByPhase[ph] || []`. Update to return the phases array directly (already structured).

**Fallback:** If `phase_name` is empty/null, skip the round header. Single-round phases (most playout brackets) render without a visible header.

**Tests:** Add test for the new helper that verifies round grouping from LeagueGroup rows with different `phase` strings.

---

## Files Changed

| File | Change |
|---|---|
| `backend/app/services/stats_service.py` | Add `ppg` to roster player dicts; extract `_build_series_rounds` helper |
| `backend/app/main.py` | Use `_build_series_rounds` when building `series_by_phase` |
| `backend/templates/team_detail.html` | Add PPG column header + cell + sort |
| `backend/templates/league_detail.html` | Nested round iteration in playoff bracket |
| `backend/tests/test_stats_service.py` | Tests for ppg in roster + series round grouping |
