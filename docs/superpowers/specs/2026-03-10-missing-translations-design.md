# Design: Add Missing Public-Facing Translations

**Date:** 2026-03-10

## Problem

All 4 locale files (en/de/fr/it) are in perfect sync with each other, and all `t.*` template references resolve correctly. However, ~30 user-facing strings in public templates are hardcoded in English rather than using translation keys. This means non-English users see English text for pagination controls, filter labels, stat abbreviations, empty states, and meta/SEO tags.

## Scope

Public-facing templates only. Admin pages excluded.

## New Translation Keys

### `t.common.*`
| Key | EN | DE | FR | IT |
|-----|----|----|----|----|
| `prev` | ← Prev | ← Zurück | ← Préc. | ← Prec. |
| `next` | Next → | Weiter → | Suiv. → | Succ. → |
| `total` | total | gesamt | total | totale |
| `vs` | vs | vs | vs | vs |
| `search_placeholder` | Search players, teams, leagues… | Spieler, Teams, Ligen suchen… | Rechercher joueurs, équipes, ligues… | Cerca giocatori, squadre, leghe… |
| `toggle_theme` | Toggle theme | Design wechseln | Changer le thème | Cambia tema |
| `toggle_menu` | Toggle menu | Menü öffnen | Ouvrir le menu | Apri menu |
| `all` | All | Alle | Tous | Tutti |
| `men` | Men | Herren | Hommes | Uomini |
| `women` | Women | Damen | Femmes | Donne |
| `gp` | GP | Sp | MJ | PG |
| `pts` | PTS | Pkt | PTS | PTS |
| `pim` | PIM | Str | PUN | MIN |

### `t.games.*` (additions)
| Key | EN | DE | FR | IT |
|-----|----|----|----|----|
| `results` | Results | Resultate | Résultats | Risultati |
| `schedule` | Schedule | Spielplan | Programme | Programma |
| `filter_level` | Level | Stufe | Niveau | Livello |
| `no_games` | No games found | Keine Spiele gefunden | Aucun match trouvé | Nessuna partita trovata |
| `count_suffix` | games | Spiele | matchs | partite |
| `upcoming` | upcoming | bevorstehend | à venir | in arrivo |

### `t.players.*` (additions)
| Key | EN | DE | FR | IT |
|-----|----|----|----|----|
| `filter_season` | Season | Saison | Saison | Stagione |
| `no_stats` | No player statistics available yet. | Noch keine Spielerstatistiken verfügbar. | Aucune statistique de joueur disponible. | Nessuna statistica disponibile. |

### `t.meta.*` (new section)
| Key | EN | DE | FR | IT |
|-----|----|----|----|----|
| `description` | Comprehensive statistics for Swiss floorball leagues, teams, games, and rankings | Umfassende Statistiken für Schweizer Unihockey-Ligen, Teams, Spiele und Ranglisten | Statistiques complètes pour les ligues, équipes, matchs et classements de l'unihockey suisse | Statistiche complete per leghe, squadre, partite e classifiche dell'unihockey svizzero |
| `og_description` | (same as description per locale) | | | |
| `keywords` | unihockey, floorball, swiss, statistics, leagues, teams, rankings | unihockey, floorball, schweiz, statistiken, ligen, teams, ranglisten | unihockey, floorball, suisse, statistiques, ligues, équipes, classements | unihockey, floorball, svizzera, statistiche, leghe, squadre, classifiche |

## Template Changes

### `base.html`
- `<meta name="description">` → `{{ t.meta.description }}`
- `<meta name="keywords">` → `{{ t.meta.keywords }}`
- `og:description` content → `{{ t.meta.og_description }}`
- `twitter:description` content → `{{ t.meta.og_description }}`
- Search `placeholder` → `{{ t.common.search_placeholder }}`
- Search `aria-label` / `title` → `{{ t.common.search_placeholder }}`
- "Toggle theme" label → `{{ t.common.toggle_theme }}`
- "Toggle dark/light mode" title → `{{ t.common.toggle_theme }}`
- "Toggle menu" aria-label → `{{ t.common.toggle_menu }}`

### `games.html`
- "Results" / "Schedule" buttons → `{{ t.games.results }}` / `{{ t.games.schedule }}`
- "games" count suffix → `{{ t.games.count_suffix }}`
- "Level" filter label → `{{ t.games.filter_level }}`
- "vs" separator → `{{ t.common.vs }}`
- "No games found" → `{{ t.games.no_games }}`

### `players.html`
- "All" / "Men" / "Women" gender options → `{{ t.common.all }}` / `{{ t.common.men }}` / `{{ t.common.women }}`
- "Season" filter label → `{{ t.players.filter_season }}`
- "GP" / "PTS" / "PIM" headers → `{{ t.common.gp }}` / `{{ t.common.pts }}` / `{{ t.common.pim }}`
- "← Prev" / "Next →" → `{{ t.common.prev }}` / `{{ t.common.next }}`
- "total" → `{{ t.common.total }}`
- "No player statistics available yet." → `{{ t.players.no_stats }}`

### `game_detail.html`
- "GP" / "PTS" / "PIM" table headers → `{{ t.common.gp }}` / `{{ t.common.pts }}` / `{{ t.common.pim }}`
- "upcoming" (unplayed game label) — NOTE: this is inside Alpine.js JS (`x-text` or `:style`), so may need to be passed as a Jinja variable to JS context rather than a direct template substitution

### `schedule.html`
- "upcoming" count label → `{{ t.games.upcoming }}`

## Files Modified

| File | Type |
|------|------|
| `backend/locales/en/messages.json` | Add ~25 keys |
| `backend/locales/de/messages.json` | Add ~25 keys |
| `backend/locales/fr/messages.json` | Add ~25 keys |
| `backend/locales/it/messages.json` | Add ~25 keys |
| `backend/templates/base.html` | ~9 substitutions |
| `backend/templates/games.html` | ~5 substitutions |
| `backend/templates/players.html` | ~10 substitutions |
| `backend/templates/game_detail.html` | ~3 substitutions |
| `backend/templates/schedule.html` | ~1 substitution |

## Verification

1. Load `/de/games` — "Resultate"/"Spielplan" buttons, "Keine Spiele gefunden", German meta description
2. Load `/fr/players` — "Hommes"/"Femmes"/"Tous", French pagination, French empty state
3. Load `/it/game/{id}` — Italian "in arrivo" for upcoming games, Italian stat abbreviations
4. Check page source `<meta name="description">` in each locale — should be locale-specific
