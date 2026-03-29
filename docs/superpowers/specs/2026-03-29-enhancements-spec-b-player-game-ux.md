# Enhancements Spec B — Player & Game UX

## Overview

Two UX enhancements to existing pages:
- Player season history: collapsible per-season rows with aggregated totals
- Game detail timeline: richer dot labels, full-detail tooltips, horizontal-scrollable mobile bar

---

## Enhancement 1: Player Season History — Collapsible Per-Season

### Problem
The player career table is a flat list of rows (one per season+team+league) with a global "show all" toggle. For players with long careers across multiple teams, this is hard to scan. Users want to see per-season totals at a glance and drill into the team/league breakdown.

### Design

**Backend (`backend/app/services/stats_service.py` — `get_player_detail`):**

Currently returns `player.career` as a flat list of row dicts. Change to group by season:

```python
player["career_by_season"] = [
    {
        "season_id": int,
        "season_text": str,          # e.g. "2024/25"
        "totals": {                  # aggregated across all rows in this season
            "gp": int,
            "g": int,
            "a": int,
            "pts": int,
            "pim": int,
            "ppg": float | None,     # pts / gp, None if gp == 0
        },
        "rows": [                    # per-team/league sub-rows (existing row dicts)
            { season_text, league, league_db_id, team_name, team_db_id, gp, g, a, pts, pim, ppg }
        ]
    },
    ...  # ordered by season_id desc (most recent first)
]
```

Keep `player.career` (flat) for the totals row — or derive totals from `career_by_season`.

Keep `player.totals` unchanged (career-wide totals row).

**Template (`backend/templates/player_detail.html`):**

Replace the current flat `{% for row in player.career %}` table with a new structure:

```
For each season in career_by_season:
  - One summary row: season_text | aggregated GP/G/A/PTS/PIM/PPG | expand/collapse button
  - When expanded (Alpine x-show): sub-rows for each team/league in that season
    (league link, team link, individual stats — same columns)
```

Alpine data per season row: `x-data="{ open: false }"`. The expand button shows `▶ / ▼`. First season (most recent) can default to `open: true`.

The global "show all" toggle (for careers > 5 seasons) is replaced by the per-season collapse pattern — all seasons always visible, each individually collapsible.

The totals row (career-wide) remains at the bottom, unchanged.

**Single-row seasons:** If a season has only one sub-row, the expand arrow is hidden and the summary row itself links directly to the league (no expansion needed — clicking would be confusing). Show a subtle indicator (no arrow) to signal it's not expandable.

**i18n:** No new keys needed.

**Tests:** Assert `career_by_season` is present in `get_player_detail` result, seasons ordered desc, totals aggregated correctly.

---

## Enhancement 2: Game Detail Timeline Rework

### Problem
- Desktop tooltip only shows a plain text label (e.g. "GOAL - 12:34 — Team · Player") — no running score, no penalty infraction details
- Mobile hides the timeline entirely and shows a plain vertical list that duplicates the events table
- Dot markers have no text — users can't read the score at a glance without hovering

### Design

**Backend (`backend/app/services/stats_service.py` — `build_timeline_events`):**

Add two new fields to each event dict:

For **goal** events — add `score` (running score string at that moment, e.g. `"2–1"`):
```python
"score": g.get("score", ""),   # already present in goals list from get_game_box_score
```

For **penalty** events — add `minutes` (already present as `p.get("minutes", 0)`):
```python
"minutes": minutes,            # already in the dict building, just expose it
"infraction": infraction,      # already built, ensure it's included
```

Both fields are already computed but not included in the event dict passed to the template. No new DB queries needed.

**Template — dot labels (`backend/templates/game_detail.html`):**

Each `.tl-marker` div currently has no text content. Add a child `<span>` with the short label:
- Goals: `e.score` (e.g. `"2–1"`)
- Penalties: `e.minutes + "'"` (e.g. `"2'"`)

Use vertical text via CSS: `writing-mode: vertical-rl; font-size: .55rem; font-weight: 700; color: white; pointer-events: none;`. The marker is 10×20px — enough for 3-char strings.

**Template — tooltip content:**

The current tooltip uses `x-text="tooltip ? tooltip.label : ''"` (single string). Replace with structured tooltip HTML showing:
- Time (period + clock)
- Team name
- Player name (if available)
- For goals: running score in large text
- For penalties: player + minutes + infraction

Use `:innerHTML` or replace with a structured `<div>` using `x-show` + `:x-text` bindings per field. The `gameTimeline` Alpine component already has `tooltip` reactive state — just expand what's rendered.

**Template — mobile bar (replacing hidden mobile list):**

Current CSS: `@media (max-width:640px) { .tl-bar { display: none; } .tl-mobile { display: flex; } }`

Change to:
```css
@media (max-width:640px) {
  .tl-bar { display: block; overflow-x: auto; -webkit-overflow-scrolling: touch; }
  .tl-mobile { display: none; }
  .tl-wrap { overflow-x: auto; }
}
```

Add `min-width: 560px` to `.tl-track` (the inner bar element) so it doesn't compress on small screens. The horizontal scroll makes the full timeline accessible on mobile. Touch events for tooltip already work via `@click.stop` on markers.

**Tests:** Unit test `build_timeline_events` to assert `score` is present in goal event dicts and `minutes`/`infraction` in penalty event dicts.

---

## Files Changed

| File | Change |
|---|---|
| `backend/app/services/stats_service.py` | `get_player_detail`: add `career_by_season`; `build_timeline_events`: add `score`/`minutes`/`infraction` to event dicts |
| `backend/templates/player_detail.html` | Replace flat career table with per-season collapsible rows |
| `backend/templates/game_detail.html` | Dot labels, structured tooltip, mobile CSS change |
| `backend/tests/test_stats_service.py` | Tests for `career_by_season` grouping + timeline event fields |
