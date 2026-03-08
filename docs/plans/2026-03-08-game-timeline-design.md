# Game Timeline Bar — Design

**Date:** 2026-03-08
**Status:** Approved

## Overview

Add a visual timeline bar to the game details page showing how a game progresses over time: goals, penalties, and period boundaries displayed in chronological order.

## Placement

Between the scorebox (score/venue/referees) and the event tabs — always visible, not hidden in a tab.

## Visual Layout

**Desktop:** Full-width horizontal bar representing the total game duration. Period dividers at 20, 40, and 60 minutes with segment labels (P1, P2, P3, OT). Goals as filled circles above the bar; penalties as tick marks below. Markers ~12px.

**Mobile:** Vertical timeline with horizontal period dividers. Events as small dot + text rows.

**Colors:** CSS custom properties from the existing theme (adapts automatically to light/dark mode). Home team = blue, away team = amber. Penalty markers use the same hue but smaller.

## Data & Positioning

**Time → position:**
```
period_start = {1: 0, 2: 20*60, 3: 40*60, OT: 60*60}
abs_seconds = period_start[period] + parse_seconds(time_in_period)
pct = abs_seconds / total_seconds * 100
```

**Total duration:**
- Regular game: 60 min (3600 s)
- OT present: 70 min (4200 s) — 10-min OT period
- Shootout events: pinned at 70 min (right edge)

**Period dividers (regular game):** 33.3% (20 min), 66.6% (40 min).
**Period dividers (with OT):** 28.6% (20 min), 57.1% (40 min), 85.7% (60 min); OT segment labeled "OT".

**Data source:** Existing `events` list in the game detail template. Server-side Jinja2 pre-computes `pct` per event and serializes as JSON inline — no new API calls.

## Implementation: Jinja2 + Alpine.js

Single Alpine.js component:

```html
<div x-data="gameTimeline({{ events_json }}, {{ total_seconds }})"
     class="game-timeline">
  <div class="timeline-bar" @click.outside="tooltip = null">
    <template x-for="e in events">
      <div class="marker"
           :class="[e.team, e.kind]"
           :style="`left: ${e.pct}%`"
           @mouseenter="tooltip = e"
           @mouseleave="tooltip = null"
           @click.stop="tooltip = (tooltip?.id === e.id ? null : e)">
      </div>
    </template>
    <div x-show="tooltip" x-transition class="tl-tooltip"
         :style="`left: clamp(0%, ${tooltip?.pct}%, calc(100% - 160px))`">
      <span x-text="tooltip?.label"></span>
    </div>
  </div>
</div>
```

`gameTimeline()` is a small inline `<script>` function (no new JS file). It holds one `tooltip` ref; hover sets it, click toggles it, outside-click clears it. `clamp()` prevents tooltip overflow at edges.

Mobile uses the same component; CSS switches to vertical layout (`flex-direction: column`, `top` instead of `left`).

## Tooltip Content

| Event kind | Format |
|---|---|
| Goal | `GOAL - 23:14 — Home Team · Player Name (assist: Other)` |
| Penalty | `PEN - 31:05 — Away Team · Player Name (2 min, hooking)` |
| Period boundary | Static label only, no tooltip |

Labels are built server-side in Python/Jinja2. Alpine.js renders them as plain text.

## Empty State

Timeline section hidden entirely via `{% if events %}` — not shown for unplayed or future games.

## Theme Support

All colors via CSS custom properties already defined in the light/dark theme. No hardcoded hex values in the timeline styles.
