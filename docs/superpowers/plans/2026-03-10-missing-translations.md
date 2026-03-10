# Missing Translations Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace ~30 hardcoded English strings in public-facing templates with `t.*` translation keys, adding those keys to all 4 locale files (en/de/fr/it).

**Architecture:** Pure find-and-replace work — add new keys to 4 locale JSON files, then substitute hardcoded strings in 5 templates. No backend logic changes. All keys follow the existing `t.section.key` pattern used throughout.

**Tech Stack:** Jinja2 templates, JSON locale files, FastAPI/Python backend

**Spec:** `docs/superpowers/specs/2026-03-10-missing-translations-design.md`

---

## Chunk 1: Add keys to locale files

### Task 1: Add keys to `en/messages.json`

**Files:**
- Modify: `backend/locales/en/messages.json`

The file is a flat-nested JSON. Keys are grouped by section (`common`, `games`, `players`, `meta`, etc.). Add new keys inside each existing section. For `meta`, add a new section.

- [ ] **Step 1: Add `t.common.*` keys**

Open `backend/locales/en/messages.json`. Find the `"common"` section and add after the last existing key in that section:

```json
"prev": "← Prev",
"next": "Next →",
"total": "total",
"vs": "vs",
"search_placeholder": "Search players, teams, leagues…",
"toggle_theme": "Toggle theme",
"toggle_menu": "Toggle menu",
"all": "All",
"men": "Men",
"women": "Women",
"gp": "GP",
"pts": "PTS",
"pim": "PIM"
```

- [ ] **Step 2: Add `t.games.*` keys**

Find the `"games"` section and add after the last existing key:

```json
"results": "Results",
"schedule": "Schedule",
"filter_level": "Level",
"no_games": "No games found",
"no_games_filtered": "No games found for this filter",
"count_suffix": "games",
"upcoming": "upcoming"
```

- [ ] **Step 3: Add `t.players.*` keys**

Find the `"players"` section and add after the last existing key:

```json
"filter_season": "Season",
"no_stats": "No player statistics available yet."
```

- [ ] **Step 4: Add `t.meta.*` section**

Add a new top-level `"meta"` section (e.g. after `"pwa"`):

```json
"meta": {
  "description": "Comprehensive statistics for Swiss floorball leagues, teams, games, and rankings",
  "og_description": "Comprehensive statistics for Swiss floorball leagues, teams, games, and rankings",
  "keywords": "unihockey, floorball, swiss, statistics, leagues, teams, rankings"
}
```

- [ ] **Step 5: Validate JSON**

```bash
cd backend && python3 -c "import json; json.load(open('locales/en/messages.json')); print('OK')"
```
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add backend/locales/en/messages.json
git commit -m "i18n: add missing translation keys to en locale"
```

---

### Task 2: Add keys to `de/messages.json`

**Files:**
- Modify: `backend/locales/de/messages.json`

Same structure as Task 1 but with German values.

- [ ] **Step 1: Add `t.common.*` keys**

```json
"prev": "← Zurück",
"next": "Weiter →",
"total": "gesamt",
"vs": "vs",
"search_placeholder": "Spieler, Teams, Ligen suchen…",
"toggle_theme": "Design wechseln",
"toggle_menu": "Menü öffnen",
"all": "Alle",
"men": "Herren",
"women": "Damen",
"gp": "Sp",
"pts": "Pkt",
"pim": "Str"
```

- [ ] **Step 2: Add `t.games.*` keys**

```json
"results": "Resultate",
"schedule": "Spielplan",
"filter_level": "Stufe",
"no_games": "Keine Spiele gefunden",
"no_games_filtered": "Keine Spiele für diesen Filter gefunden",
"count_suffix": "Spiele",
"upcoming": "bevorstehend"
```

- [ ] **Step 3: Add `t.players.*` keys**

```json
"filter_season": "Saison",
"no_stats": "Noch keine Spielerstatistiken verfügbar."
```

- [ ] **Step 4: Add `t.meta.*` section**

```json
"meta": {
  "description": "Umfassende Statistiken für Schweizer Unihockey-Ligen, Teams, Spiele und Ranglisten",
  "og_description": "Umfassende Statistiken für Schweizer Unihockey-Ligen, Teams, Spiele und Ranglisten",
  "keywords": "unihockey, floorball, schweiz, statistiken, ligen, teams, ranglisten"
}
```

- [ ] **Step 5: Validate JSON**

```bash
python3 -c "import json; json.load(open('locales/de/messages.json')); print('OK')"
```

- [ ] **Step 6: Commit**

```bash
git add backend/locales/de/messages.json
git commit -m "i18n: add missing translation keys to de locale"
```

---

### Task 3: Add keys to `fr/messages.json`

**Files:**
- Modify: `backend/locales/fr/messages.json`

- [ ] **Step 1: Add `t.common.*` keys**

```json
"prev": "← Préc.",
"next": "Suiv. →",
"total": "total",
"vs": "vs",
"search_placeholder": "Rechercher joueurs, équipes, ligues…",
"toggle_theme": "Changer le thème",
"toggle_menu": "Ouvrir le menu",
"all": "Tous",
"men": "Hommes",
"women": "Femmes",
"gp": "MJ",
"pts": "PTS",
"pim": "PUN"
```

- [ ] **Step 2: Add `t.games.*` keys**

```json
"results": "Résultats",
"schedule": "Programme",
"filter_level": "Niveau",
"no_games": "Aucun match trouvé",
"no_games_filtered": "Aucun match trouvé pour ce filtre",
"count_suffix": "matchs",
"upcoming": "à venir"
```

- [ ] **Step 3: Add `t.players.*` keys**

```json
"filter_season": "Saison",
"no_stats": "Aucune statistique de joueur disponible."
```

- [ ] **Step 4: Add `t.meta.*` section**

```json
"meta": {
  "description": "Statistiques complètes pour les ligues, équipes, matchs et classements de l'unihockey suisse",
  "og_description": "Statistiques complètes pour les ligues, équipes, matchs et classements de l'unihockey suisse",
  "keywords": "unihockey, floorball, suisse, statistiques, ligues, équipes, classements"
}
```

- [ ] **Step 5: Validate JSON**

```bash
python3 -c "import json; json.load(open('locales/fr/messages.json')); print('OK')"
```

- [ ] **Step 6: Commit**

```bash
git add backend/locales/fr/messages.json
git commit -m "i18n: add missing translation keys to fr locale"
```

---

### Task 4: Add keys to `it/messages.json`

**Files:**
- Modify: `backend/locales/it/messages.json`

- [ ] **Step 1: Add `t.common.*` keys**

```json
"prev": "← Prec.",
"next": "Succ. →",
"total": "totale",
"vs": "vs",
"search_placeholder": "Cerca giocatori, squadre, leghe…",
"toggle_theme": "Cambia tema",
"toggle_menu": "Apri menu",
"all": "Tutti",
"men": "Uomini",
"women": "Donne",
"gp": "PG",
"pts": "PTS",
"pim": "MIN"
```

- [ ] **Step 2: Add `t.games.*` keys**

```json
"results": "Risultati",
"schedule": "Programma",
"filter_level": "Livello",
"no_games": "Nessuna partita trovata",
"no_games_filtered": "Nessuna partita trovata per questo filtro",
"count_suffix": "partite",
"upcoming": "in arrivo"
```

- [ ] **Step 3: Add `t.players.*` keys**

```json
"filter_season": "Stagione",
"no_stats": "Nessuna statistica disponibile."
```

- [ ] **Step 4: Add `t.meta.*` section**

```json
"meta": {
  "description": "Statistiche complete per leghe, squadre, partite e classifiche dell'unihockey svizzero",
  "og_description": "Statistiche complete per leghe, squadre, partite e classifiche dell'unihockey svizzero",
  "keywords": "unihockey, floorball, svizzera, statistiche, leghe, squadre, classifiche"
}
```

- [ ] **Step 5: Validate JSON**

```bash
python3 -c "import json; json.load(open('locales/it/messages.json')); print('OK')"
```

- [ ] **Step 6: Commit**

```bash
git add backend/locales/it/messages.json
git commit -m "i18n: add missing translation keys to it locale"
```

---

## Chunk 2: Update templates

### Task 5: Update `base.html`

**Files:**
- Modify: `backend/templates/base.html`

Lines to change (reference line numbers may shift by a few after edits):

- [ ] **Step 1: Update meta description tag (line ~9)**

```html
<!-- Before -->
<meta name="description" content="{% block description %}Unihockey Stats - Comprehensive statistics for Swiss floorball leagues, teams, games, and rankings{% endblock %}">

<!-- After -->
<meta name="description" content="{% block description %}{{ t.meta.description }}{% endblock %}">
```

- [ ] **Step 2: Update meta keywords tag (line ~10)**

```html
<!-- Before -->
<meta name="keywords" content="{% block keywords %}unihockey, floorball, swiss, switzerland, sports, leagues, teams, statistics, rankings{% endblock %}">

<!-- After -->
<meta name="keywords" content="{% block keywords %}{{ t.meta.keywords }}{% endblock %}">
```

- [ ] **Step 3: Update og:description (line ~18)**

```html
<!-- Before -->
<meta property="og:description" content="{% block og_description %}Comprehensive statistics for Swiss floorball leagues, teams, games, and rankings{% endblock %}">

<!-- After -->
<meta property="og:description" content="{% block og_description %}{{ t.meta.og_description }}{% endblock %}">
```

- [ ] **Step 4: Update twitter:description (line ~26)**

```html
<!-- Before -->
<meta name="twitter:description" content="{% block twitter_description %}Comprehensive statistics for Swiss floorball leagues, teams, and rankings{% endblock %}">

<!-- After -->
<meta name="twitter:description" content="{% block twitter_description %}{{ t.meta.og_description }}{% endblock %}">
```

- [ ] **Step 5: Update mobile theme toggle label (line ~117-119)**

```html
<!-- Before -->
<button class="theme-toggle mobile-theme-btn" onclick="themeManager.toggle()" aria-label="Toggle theme">
    ...
    <span class="mobile-theme-label">Toggle theme</span>

<!-- After -->
<button class="theme-toggle mobile-theme-btn" onclick="themeManager.toggle()" aria-label="{{ t.common.toggle_theme }}">
    ...
    <span class="mobile-theme-label">{{ t.common.toggle_theme }}</span>
```

- [ ] **Step 6: Update search button aria-label and placeholder (lines ~130, 131, 147)**

```html
<!-- Before -->
aria-label="Search"
title="Search"
...
placeholder="Search players, teams, leagues…"

<!-- After -->
aria-label="{{ t.common.search_placeholder }}"
title="{{ t.common.search_placeholder }}"
...
placeholder="{{ t.common.search_placeholder }}"
```

- [ ] **Step 7: Update desktop theme toggle (line ~160-161)**

```html
<!-- Before -->
aria-label="Toggle theme"
title="Toggle dark/light mode"

<!-- After -->
aria-label="{{ t.common.toggle_theme }}"
title="{{ t.common.toggle_theme }}"
```

- [ ] **Step 8: Update hamburger menu aria-label (line ~164)**

```html
<!-- Before -->
aria-label="Toggle menu"

<!-- After -->
aria-label="{{ t.common.toggle_menu }}"
```

- [ ] **Step 9: Smoke-test by starting the dev server and loading `/de/` in a browser**

```bash
cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000
```

Check page source for `<meta name="description">` — should be in German.

- [ ] **Step 10: Commit**

```bash
git add backend/templates/base.html
git commit -m "i18n: replace hardcoded strings in base.html"
```

---

### Task 6: Update `games.html`

**Files:**
- Modify: `backend/templates/games.html`

- [ ] **Step 1: Update count suffix (line ~10)**

```html
<!-- Before -->
<span style="font-size:.875rem;color:var(--gray-500);">{{ total }} games</span>

<!-- After -->
<span style="font-size:.875rem;color:var(--gray-500);">{{ total }} {{ t.games.count_suffix }}</span>
```

- [ ] **Step 2: Update Results/Schedule mode buttons (lines ~16-17)**

```html
<!-- Before -->
<a href="?mode=results&{{ fp }}" class="sort-btn{% if mode == 'results' %} active{% endif %}">Results</a>
<a href="?mode=schedule&{{ fp }}" class="sort-btn{% if mode == 'schedule' %} active{% endif %}">Schedule</a>

<!-- After -->
<a href="?mode=results&{{ fp }}" class="sort-btn{% if mode == 'results' %} active{% endif %}">{{ t.games.results }}</a>
<a href="?mode=schedule&{{ fp }}" class="sort-btn{% if mode == 'schedule' %} active{% endif %}">{{ t.games.schedule }}</a>
```

- [ ] **Step 3: Update Level filter label (line ~47)**

```html
<!-- Before -->
<span class="filter-bar-label">Level</span>

<!-- After -->
<span class="filter-bar-label">{{ t.games.filter_level }}</span>
```

- [ ] **Step 4: Update vs separator (line ~74)**

```html
<!-- Before -->
<div class="game-col-vs">vs</div>

<!-- After -->
<div class="game-col-vs">{{ t.common.vs }}</div>
```

- [ ] **Step 5: Update empty state message (line ~111)**

```html
<!-- Before -->
<p>No games found{% if sex != 'all' or age != 'all' or field != 'all' or level != 'all' %} for this filter{% endif %}.</p>

<!-- After -->
<p>{% if sex != 'all' or age != 'all' or field != 'all' or level != 'all' %}{{ t.games.no_games_filtered }}{% else %}{{ t.games.no_games }}{% endif %}.</p>
```

- [ ] **Step 6: Update pagination controls**

`games.html` also has the same pagination pattern as `players.html`. Find the pagination block and replace:

```html
<!-- Before -->
class="page-link wide">← Prev</a>
...
class="page-link wide">Next →</a>
...
<span class="pagination-total">{{ total }} total</span>

<!-- After -->
class="page-link wide">{{ t.common.prev }}</a>
...
class="page-link wide">{{ t.common.next }}</a>
...
<span class="pagination-total">{{ total }} {{ t.common.total }}</span>
```

- [ ] **Step 7: Commit**

```bash
git add backend/templates/games.html
git commit -m "i18n: replace hardcoded strings in games.html"
```

---

### Task 7: Update `players.html`

**Files:**
- Modify: `backend/templates/players.html`

- [ ] **Step 1: Update PIM sort option label (line ~11)**

```html
<!-- Before -->
{% for o, label in [('points', t.players.order_points),('goals', t.players.order_goals),('assists', t.players.order_assists),('pim','PIM')] %}

<!-- After -->
{% for o, label in [('points', t.players.order_points),('goals', t.players.order_goals),('assists', t.players.order_assists),('pim', t.common.pim)] %}
```

- [ ] **Step 2: Update Season filter label (line ~26)**

```html
<!-- Before -->
<label class="filter-label">Season</label>

<!-- After -->
<label class="filter-label">{{ t.players.filter_season }}</label>
```

- [ ] **Step 3: Update gender filter options (line ~35)**

```html
<!-- Before -->
{% for gkey, glabel in [('all','All'), ('men','Men'), ('women','Women')] %}

<!-- After -->
{% for gkey, glabel in [('all', t.common.all), ('men', t.common.men), ('women', t.common.women)] %}
```

- [ ] **Step 4: Update GP/PTS/PIM table headers (lines ~73, 76, 77)**

```html
<!-- Before -->
<th class="col-narrow">GP</th>
...
<th class="col-narrow" style="font-weight:700;">PTS</th>
<th class="col-narrow">PIM</th>

<!-- After -->
<th class="col-narrow">{{ t.common.gp }}</th>
...
<th class="col-narrow" style="font-weight:700;">{{ t.common.pts }}</th>
<th class="col-narrow">{{ t.common.pim }}</th>
```

- [ ] **Step 5: Update empty state message (line ~102)**

```html
<!-- Before -->
<p>No player statistics available yet.</p>

<!-- After -->
<p>{{ t.players.no_stats }}</p>
```

- [ ] **Step 6: Update pagination controls (lines ~110, 118, 120)**

```html
<!-- Before -->
class="page-link wide">← Prev</a>
...
class="page-link wide">Next →</a>
...
<span class="pagination-total">{{ total }} total</span>

<!-- After -->
class="page-link wide">{{ t.common.prev }}</a>
...
class="page-link wide">{{ t.common.next }}</a>
...
<span class="pagination-total">{{ total }} {{ t.common.total }}</span>
```

- [ ] **Step 7: Commit**

```bash
git add backend/templates/players.html
git commit -m "i18n: replace hardcoded strings in players.html"
```

---

### Task 8: Update `game_detail.html`

**Files:**
- Modify: `backend/templates/game_detail.html`

Note: GP/PTS/PIM appear in two roster tables (home + away), and in the standings table. The `PTS&#9733;` (star) is for game PTS — replace only "PTS" and keep the `&#9733;`.

- [ ] **Step 1: Update roster table GP/PTS headers (lines ~674-679, repeated ~713-718)**

Replace all occurrences of bare `GP` and `PTS` in `<th>` elements (there are 2 identical roster tables):

```html
<!-- Before -->
>GP<span
>PTS&#9733;<span
>PTS<span   (season PTS column)

<!-- After -->
>{{ t.common.gp }}<span
>{{ t.common.pts }}&#9733;<span
>{{ t.common.pts }}<span
```

Use find-and-replace carefully — the pattern `>GP<span` is unique enough. There are exactly 2 occurrences of each (home table + away table).

- [ ] **Step 2: Update standings table GP/PTS headers (lines ~960, 968)**

```html
<!-- Before -->
<th style="text-align:center;">GP</th>
...
<th style="text-align:center;font-weight:700;color:var(--gray-700);">PTS</th>

<!-- After -->
<th style="text-align:center;">{{ t.common.gp }}</th>
...
<th style="text-align:center;font-weight:700;color:var(--gray-700);">{{ t.common.pts }}</th>
```

- [ ] **Step 3: Update "upcoming" label in Alpine.js template (line ~1051)**

This is inside a `<template x-if="!g.played">` block — Jinja renders before Alpine.js, so `{{ t.games.upcoming }}` works fine here:

```html
<!-- Before -->
<span style="font-size:.72rem;color:var(--gray-400);font-style:italic;">upcoming</span>

<!-- After -->
<span style="font-size:.72rem;color:var(--gray-400);font-style:italic;">{{ t.games.upcoming }}</span>
```

- [ ] **Step 4: Commit**

```bash
git add backend/templates/game_detail.html
git commit -m "i18n: replace hardcoded strings in game_detail.html"
```

---

### Task 9: Update `schedule.html`

**Files:**
- Modify: `backend/templates/schedule.html`

- [ ] **Step 1: Update "upcoming" count suffix (line ~10)**

```html
<!-- Before -->
<span style="font-size:.875rem;color:var(--gray-500);">{{ total }} upcoming</span>

<!-- After -->
<span style="font-size:.875rem;color:var(--gray-500);">{{ total }} {{ t.games.upcoming }}</span>
```

- [ ] **Step 2: Update vs separator (line ~61)**

```html
<!-- Before -->
<div class="game-col-vs">vs</div>

<!-- After -->
<div class="game-col-vs">{{ t.common.vs }}</div>
```

- [ ] **Step 3: Update empty state (line ~75)**

```html
<!-- Before -->
<p>No upcoming games found{% if sex != 'all' or age != 'all' or field != 'all' %} for this filter{% endif %}.</p>

<!-- After -->
<p>{% if sex != 'all' or age != 'all' or field != 'all' %}{{ t.games.no_games_filtered }}{% else %}{{ t.games.no_games }}{% endif %}.</p>
```

- [ ] **Step 4: Update pagination controls**

`schedule.html` also has pagination. Replace:

```html
<!-- Before -->
class="page-link wide">← Prev</a>
...
class="page-link wide">Next →</a>
...
<span class="pagination-total">{{ total }} total</span>

<!-- After -->
class="page-link wide">{{ t.common.prev }}</a>
...
class="page-link wide">{{ t.common.next }}</a>
...
<span class="pagination-total">{{ total }} {{ t.common.total }}</span>
```

- [ ] **Step 5: Commit**

```bash
git add backend/templates/schedule.html
git commit -m "i18n: replace hardcoded strings in schedule.html"
```

---

## Chunk 3: Verification

### Task 10: End-to-end verification

- [ ] **Step 1: Start dev server**

```bash
cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000
```

- [ ] **Step 2: Verify German games page**

Load `http://localhost:8000/de/games` — confirm:
- Buttons show "Resultate" / "Spielplan"
- Count shows "X Spiele"
- Empty state (if no games): "Keine Spiele gefunden"

- [ ] **Step 3: Verify French players page**

Load `http://localhost:8000/fr/players` — confirm:
- Gender filter shows "Tous / Hommes / Femmes"
- Season label shows "Saison"
- Table headers show "MJ / PTS / PUN"
- Pagination shows "← Préc." / "Suiv. →" / "X total"

- [ ] **Step 4: Verify Italian game detail page**

Load any playoff game at `http://localhost:8000/it/game/<id>` — confirm:
- Unplayed series games show "in arrivo"
- Roster table headers show "PG / PTS / MIN"

- [ ] **Step 5: Check meta tags per locale**

```bash
curl -s http://localhost:8000/de/ | grep 'meta name="description"'
curl -s http://localhost:8000/fr/ | grep 'meta name="description"'
curl -s http://localhost:8000/it/ | grep 'meta name="description"'
```

Each should show the locale-specific description.

- [ ] **Step 6: Final commit and push**

```bash
git push
```
