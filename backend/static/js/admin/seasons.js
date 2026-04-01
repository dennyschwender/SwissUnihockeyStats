// backend/static/js/admin/seasons.js
import { fetchJSON } from './utils.js';

/* =======================================================
   Module-level state (seasons tab owns these)
======================================================= */
let _freshnessMap = {};
let _seasonFilter = { min_season: null, excluded_seasons: [] };
let _completenessMap = {};  // season_id -> completeness row

/* task name -> entity_type (matches scheduler POLICIES) */
const TASK_TO_ENTITY = {
  clubs: 'clubs', teams: 'teams', players: 'players',
  player_stats: 'player_stats', game_lineups: 'game_lineups',
  player_game_stats: 'player_game_stats',
  leagues: 'leagues', groups: 'league_groups', games: 'games', events: 'game_events',
};

/* =======================================================
   Setters called by stats.js after loading scheduler-diag
======================================================= */
export function setFreshnessMap(map) { _freshnessMap = map; }
export function setSeasonFilter(filter) { _seasonFilter = filter; }
export function setCompletenessMap(map) { _completenessMap = map; }

/* =======================================================
   Season filter helper
======================================================= */
export function isSeasonFiltered(sid) {
  if (_seasonFilter.min_season != null && sid < _seasonFilter.min_season) return true;
  if ((_seasonFilter.excluded_seasons || []).includes(sid)) return true;
  return false;
}

/* =======================================================
   Season accordion
======================================================= */
export function renderSeasons(seasons) {
  const container = document.getElementById('seasons-container');

  // preserve open state across re-renders
  const open = new Set(
    [...container.querySelectorAll('.season-body.open')]
      .map(el => el.dataset.sid)
  );

  container.innerHTML = seasons.map(s =>
    buildSeasonCard(s, open.has(String(s.season_id)))
  ).join('');
}

function buildSeasonCard(s, isOpen) {
  const sid  = s.season_id;
  const year = sid + '/' + String(sid + 1).slice(-2);

  const summaryChips = [
    schip(s.clubs,         'clubs'),
    schip(s.teams,         'teams'),
    schip(s.team_players,  'players'),
    schip(s.player_stats,  'stats'),
    schip(s.leagues,       'leagues'),
    schip(s.league_groups, 'groups'),
    schip(s.games,         'games'),
    schip(s.game_players,  'lineups'),
    schip(s.game_events,   'events'),
  ].join('');

  const currentBadge = s.is_current ? ' <span class="current-badge">&#9733; current</span>' : '';
  const currentCls = s.is_current ? ' current-season' : '';
  const currentBtnCls = s.is_current ? 'btn-red' : 'btn-yellow';
  const currentBtnTxt = s.is_current ? '&#9733; Unset Current' : '&#9734; Set as Current';
  const currentBtnTitle = s.is_current
    ? 'Remove current-season flag'
    : 'Mark as current season \u2014 future seasons will be skipped during indexing';
  const chevOpen = isOpen ? ' open' : '';
  const bodyOpen = isOpen ? ' open' : '';

  return (
    '\n<div class="season-card' + currentCls + '">' +
    '\n  <div class="season-header" onclick="toggleSeason(' + sid + ')">' +
    '\n    <span class="season-year">' + year + currentBadge + '</span>' +
    '\n    <div class="season-chips">' + summaryChips + buildCompletenessChip(s) + buildGamesCompleteness(sid) + buildFreezeStatusBadge(sid) + buildSeasonFreshSummary(sid) + '</div>' +
    '\n    <span class="chevron' + chevOpen + '" id="chv-' + sid + '">\u25b6</span>' +
    '\n  </div>' +
    '\n  <div class="season-body' + bodyOpen + '" id="sbody-' + sid + '" data-sid="' + sid + '">' +
    '\n' +
    '\n    <div class="task-group-label">Clubs Path</div>' +
    '\n    ' + trowTier(sid,'clubs',   'Clubs',                  [p(s.clubs,'clubs')]) +
    '\n    ' + trowTier(sid,'teams',   'Teams (per club)',        [p(s.clubs,'clubs'), p(s.teams,'teams')]) +
    '\n    ' + trowTier(sid,'players',          'Players (per team)',         [p(s.teams,'teams'), p(s.team_players,'roster')]) +
    '\n    ' + trowTier(sid,'player_stats',      'Player Statistics',          [p(s.team_players,'roster'), p(s.player_stats,'stats')]) +
    '\n    ' + trowTier(sid,'game_lineups',      'Game Lineups',               [p(s.games,'games'), p(s.game_players,'lineups')]) +
    '\n    ' + trowTier(sid,'player_game_stats', 'Player Game Stats (G/A/PIM)',[p(s.game_players,'lineups'), p(s.player_stats,'stats')]) +
    '\n' +
    '\n    <div class="task-group-label">Leagues Path</div>' +
    '\n    ' + trowTier(sid,'leagues', 'Leagues',             [p(s.leagues,'leagues')]) +
    '\n    ' + trowTier(sid,'groups',  'League Groups',       [p(s.leagues,'leagues'), p(s.league_groups,'groups')]) +
    '\n    ' + trowTier(sid,'games',   'Games (per league)',  [p(s.league_groups,'groups'), p(s.games,'games')]) +
    '\n    ' + trowEvents(sid, s) +
    '\n' +
    '\n    <div class="quick-row">' +
    '\n      <button class="btn btn-blue btn-sm"  onclick="triggerIndex(' + sid + ',\'clubs_path\')">&#9654; Clubs Path</button>' +
    '\n      <button class="btn btn-blue btn-sm"  onclick="triggerIndex(' + sid + ',\'leagues_path\')">&#9654; Leagues Path</button>' +
    '\n      <button class="btn btn-green btn-sm" onclick="triggerIndex(' + sid + ',\'full\')">&#9889; Full Season</button>' +
    '\n      <button class="btn btn-sm ' + currentBtnCls + '" onclick="setCurrentSeason(' + sid + ', ' + s.is_current + ')" title="' + currentBtnTitle + '">' + currentBtnTxt + '</button>' +
    '\n      ' + buildFreezeButton(sid) +
    '\n      <button class="btn btn-red btn-sm"   onclick="deleteLayer(' + sid + ',\'all\')">&#128465; Delete Season</button>' +
    '\n      <label>' +
    '\n        <input type="checkbox" id="force-' + sid + '">' +
    '\n        Force re-index' +
    '\n      </label>' +
    '\n    </div>' +
    '\n  </div>' +
    '\n</div>'
  );
}

function schip(n, label) {
  const cls = n > 0 ? 'ok' : 'empty';
  return '<span class="s-chip ' + cls + '">' + window.fmt(n) + ' ' + label + '</span>';
}
function p(n, label) {
  const cls = n > 0 ? ' has-data' : '';
  return '<span class="count-pill' + cls + '">' + window.fmt(n) + ' ' + label + '</span>';
}
const _TIER_LABELS = [
  [1,'T1 \u2014 NLA/L-UPL only'],
  [2,'T2 \u2014 + NLB, U21A/U18A/U16A'],
  [3,'T3 \u2014 + 1. Liga, U21B/U18B/U16B'],
  [4,'T4 \u2014 + 2. Liga, U21C/U18C/U16C'],
  [5,'T5 \u2014 + 3. Liga, U21D'],
  [6,'T6 \u2014 All (+ 4./5. Liga, Regional, Cups)'],
  [7,'T7 \u2014 Everything'],
];
function _tierOpts(task) {
  const def = window._defaultTiers[task] != null ? window._defaultTiers[task] : 2;
  return _TIER_LABELS.map(function(pair) {
    return '<option value="' + pair[0] + '"' + (pair[0] === def ? ' selected' : '') + '>' + pair[1] + '</option>';
  }).join('');
}
function trowTier(sid, task, name, counts) {
  return (
    '\n<div class="task-row">' +
    '\n  <span class="task-name">' + name + '</span>' +
    '\n  <div class="task-counts">' + counts.join('') + freshnessBadge(sid, task) +
    '\n    <select id="tier-' + task + '-' + sid + '" class="tier-select" title="Max league tier">' + _tierOpts(task) + '</select>' +
    '\n  </div>' +
    '\n  <div class="task-btns">' +
    '\n    <button class="btn btn-sm" onclick="triggerIndexTiered(' + sid + ',\'' + task + '\')">&#9654; Index</button>' +
    '\n    <button class="btn btn-sm btn-red" onclick="deleteLayer(' + sid + ',\'' + task + '\')" title="Delete ' + name + ' data for this season">&#128465;</button>' +
    '\n  </div>' +
    '\n</div>'
  );
}
function trowEvents(sid, s) {
  const tierOptions = _TIER_LABELS.map(function(pair) {
    return '<option value="' + pair[0] + '"' + (pair[0] === window._defaultTiers.events ? ' selected' : '') + '>' + pair[1] + '</option>';
  }).join('');
  return (
    '\n<div class="task-row">' +
    '\n  <span class="task-name">Game Events (finished)</span>' +
    '\n  <div class="task-counts">' +
    '\n    ' + p(s.games,'games') + ' ' + p(s.game_events,'events') + freshnessBadge(sid, 'events') +
    '\n    <select id="tier-events-' + sid + '" class="tier-select" title="Max league tier to fetch events for">' +
    '\n      ' + tierOptions +
    '\n    </select>' +
    '\n  </div>' +
    '\n  <div class="task-btns">' +
    '\n    <button class="btn btn-sm" onclick="triggerIndexEvents(' + sid + ')">&#9654; Index</button>' +
    '\n    <button class="btn btn-sm btn-red" onclick="deleteLayer(' + sid + ',\'events\')" title="Delete Game Events data for this season">&#128465;</button>' +
    '\n  </div>' +
    '\n</div>'
  );
}
function forceFor(sid) {
  const cb = document.getElementById('force-' + sid);
  return cb ? cb.checked : false;
}

function toggleSeason(sid) {
  document.getElementById('sbody-' + sid).classList.toggle('open');
  document.getElementById('chv-'   + sid).classList.toggle('open');
}

/* =======================================================
   Freshness helpers
======================================================= */
function freshnessBadge(sid, task) {
  const entityType = TASK_TO_ENTITY[task] || task;
  let row = _freshnessMap[entityType + ':' + sid];
  // Scheduler tracks some tasks per-tier (e.g. player_stats_t1...t6) -- fall back to any tier variant
  if (!row) {
    for (let t = 1; t <= 6 && !row; t++) row = _freshnessMap[entityType + '_t' + t + ':' + sid];
  }
  if (!row) return '';
  const skipRow = row.current_only && !row.is_current;
  if (skipRow) return '<span class="fresh-badge skip" title="Past season \u2014 not auto-scheduled">past</span>';
  const cls = row.status === 'FRESH' ? 'ok' : (row.status === 'NEVER_SYNCED' ? 'fail' : 'warn');
  const lbl = row.status === 'FRESH' ? '\u2713 fresh' : (row.status === 'NEVER_SYNCED' ? '\u26a0 never' : '\u26a1 stale');
  const maxAgeStr = row.max_age_h >= 24 ? Math.round(row.max_age_h / 24) + 'd' : row.max_age_h + 'h';
  const tip = 'Next: ' + row.next_run + ' \u00b7 max age: ' + maxAgeStr;
  return '<span class="fresh-badge ' + cls + '" title="' + tip + '">' + lbl + '</span>'
       + '<span class="next-run-pill" title="' + tip + '">' + row.next_run + '</span>';
}

function buildGamesCompleteness(sid) {
  const c = _completenessMap[sid];
  if (!c) return '';
  const total = c.games_total || 0;
  if (total === 0) return '';
  const finished = c.games_finished || 0;
  const pct = c.games_pct || 0;
  const check = pct === 100 ? ' \u2713' : '';
  const tip = pct === 100 ? 'All games finished' : finished + ' of ' + total + ' games finished (' + pct + '%)';
  const cls = pct === 100 ? 'ok' : (pct >= 80 ? 'warn' : '');
  return '<span class="s-chip ' + cls + '" title="' + tip + '">' + finished + '/' + total + ' games' + check + '</span>';
}

function buildFreezeStatusBadge(sid) {
  const c = _completenessMap[sid];
  if (!c) return '';
  if (c.is_frozen)
    return '<span class="s-chip" style="background:#30363d;color:#8b949e;border-color:#484f58">\u2744 Frozen</span>';
  if (c.is_complete)
    return '<span class="s-chip ok" style="background:#1e3a1e;color:#3fb950;border-color:#238636">\u2705 Complete</span>';
  return '';
}

function buildFreezeButton(sid) {
  const c = _completenessMap[sid];
  if (!c) return '';
  if (c.is_frozen)
    return '<button class="btn btn-sm" style="background:#21262d;border-color:#30363d;color:#8b949e" onclick="unfreezeSeason(' + sid + ')" title="Unfreeze season \u2014 scheduler will resume indexing">\u2744 Unfreeze</button>';
  if (c.is_complete)
    return '<button class="btn btn-sm" style="background:#1e3a1e;border-color:#238636;color:#3fb950" onclick="freezeSeason(' + sid + ')" title="Freeze season \u2014 scheduler will skip indexing">\u2744 Freeze</button>';
  return '';
}

function buildCompletenessChip(s) {
  // Layers we expect to be > 0 for a fully-indexed season, with friendly labels.
  // game_events is omitted -- it's optional (only indexed for top tiers).
  const layers = [
    [s.clubs,        'clubs'],
    [s.leagues,      'leagues'],
    [s.league_groups,'groups'],
    [s.teams,        'teams'],
    [s.games,        'games'],
    [s.team_players, 'roster'],
    [s.game_players, 'lineups'],
    [s.player_stats, 'player stats'],
  ];
  const missing = layers.filter(function(pair) { return !pair[0] || pair[0] === 0; }).map(function(pair) { return pair[1]; });
  const total   = layers.length;
  const done    = total - missing.length;

  if (missing.length === total)
    return '<span class="s-chip empty" title="No data indexed yet">\u2b1c empty</span>';
  if (missing.length === 0)
    return '<span class="s-chip ok" title="All ' + total + ' data layers indexed">\u2705 complete</span>';

  const tip = 'Missing: ' + missing.join(', ');
  const pct = Math.round(done / total * 100);
  const cls = missing.length <= 2 ? 'warn' : '';
  return '<span class="s-chip ' + cls + '" title="' + tip + '">\ud83d\udcca ' + done + '/' + total + ' layers (' + pct + '%)</span>';
}

// Entity types that have a visible task row in the season accordion.
// Policies whose entity_type is NOT in this set are background-only jobs
// (e.g. upcoming_games_*, post_game_completion, compute_player_stats) that
// have no rendered row in the dropdown, so they must not be counted in the
// summary chip — otherwise the chip says "N never synced" but expanding the
// season shows all rows green.
const _ACCORDION_ENTITY_TYPES = new Set([
  'clubs', 'teams', 'players', 'player_stats', 'game_lineups', 'player_game_stats',
  'leagues', 'league_groups', 'games', 'game_events',
  'player_stats_t1', 'player_stats_t2', 'player_stats_t3',
  'player_stats_t4', 'player_stats_t5', 'player_stats_t6',
  'player_game_stats_t4', 'player_game_stats_t5', 'player_game_stats_t6',
]);

function buildSeasonFreshSummary(sid) {
  const relevant = Object.entries(_freshnessMap)
    .filter(function(entry) { return entry[0].endsWith(':' + sid); })
    .map(function(entry) { return entry[1]; })
    .filter(function(v) { return !(v.current_only && !v.is_current); })
    // Only count entity types that actually have a visible row in the accordion.
    // Background-only policies (upcoming_games_*, post_game_completion,
    // compute_player_stats) are tracked in the freshness map but not rendered
    // as rows, so excluding them prevents the "N never synced" phantom count.
    .filter(function(v) { return _ACCORDION_ENTITY_TYPES.has(v.entity_type); });
  if (!relevant.length) return '';
  // Exclude FROZEN rows -- past seasons are intentionally frozen by the scheduler
  // once indexed (data doesn't change), so they should never appear as warnings.
  // Also exclude NEVER_SYNCED rows on past (non-current) seasons where current_only
  // is false -- these are tier policies (player_stats_t2+, player_game_stats_t4+)
  // added after the season ended; the scheduler will never run them for past seasons,
  // so they are effectively frozen-with-no-data and should not count as warnings.
  // Exclude game_events -- its 10-minute TTL means it is almost always stale
  // between scheduler runs; its live status is visible in the diag table.
  const active = relevant.filter(function(v) {
    if (v.status === 'FROZEN') return false;
    if (v.entity_type === 'game_events') return false;
    if (v.status === 'NEVER_SYNCED' && !v.is_current && !v.current_only) return false;
    return true;
  });
  const neverRows = active.filter(function(v) { return v.status === 'NEVER_SYNCED'; });
  const staleRows = active.filter(function(v) { return v.status === 'STALE'; });
  const neverCount = neverRows.length;
  const staleCount = staleRows.length;
  const neverNames = neverRows.map(function(v) { return v.label || v.policy; });
  const staleNames = staleRows.map(function(v) { return v.label || v.policy; });
  if (neverCount && staleCount) {
    const tip = 'Never synced: ' + neverNames.join(', ') + '\nStale: ' + staleNames.join(', ');
    return '<span class="s-chip" style="background:#2d1214;color:#f85149;border-color:#da3633" title="' + tip + '">\u26a0 ' + neverCount + ' never synced</span>';
  }
  if (neverCount)
    return '<span class="s-chip" style="background:#2d1214;color:#f85149;border-color:#da3633" title="Never synced: ' + neverNames.join(', ') + '">\u26a0 ' + neverCount + ' never synced</span>';
  if (staleCount)
    return '<span class="s-chip warn" title="Stale: ' + staleNames.join(', ') + '">\u26a1 ' + staleCount + ' stale</span>';
  return '<span class="s-chip ok" title="All data types fresh">\u2713 all fresh</span>';
}

/* =======================================================
   Trigger + actions
======================================================= */
async function setCurrentSeason(sid, isCurrent) {
  if (isCurrent) {
    if (!confirm('Remove the "current season" flag from ' + sid + '/' + String(sid+1).slice(-2) + '?')) return;
  }
  const d = await fetchJSON('/admin/api/season/' + sid + '/set-current', { method: 'POST' });
  if (!d) { window.log('error', 'Failed: set-current request failed'); return; }
  window.log('ok', '\u2605 Season ' + sid + '/' + String(sid+1).slice(-2) + ' marked as current');
  window.loadStats();
}
async function pullSeasons() {
  const btn = document.getElementById('pull-seasons-btn');
  if (btn) btn.disabled = true;
  window.log('info', '\u21bb Fetching seasons list from API\u2026');
  try {
    const d = await fetchJSON('/admin/api/index', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ season: 0, task: 'seasons', force: true }),
    });
    if (!d) { window.log('error', 'Rejected: pull-seasons request failed'); return; }
    window.log('info', 'Job ' + d.job_id + ' queued \u2014 ' + d.label);
    window.registerJob(d);
    // Refresh stats once job completes so season list updates
    setTimeout(window.loadStats, 3000);
  } finally {
    if (btn) btn.disabled = false;
  }
}
async function triggerIndex(season, task) {
  const force = forceFor(season);
  window.log('info', '\u25b6 season=' + season + '  task=' + task + '  force=' + force);
  const d = await fetchJSON('/admin/api/index', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ season, task, force: !!force }),
  });
  if (!d) { window.log('error', 'Rejected: index request failed'); return; }
  window.log('info', 'Job ' + d.job_id + ' queued \u2014 ' + d.label);
  window.registerJob(d);
}
async function triggerIndexTiered(season, task) {
  const force = forceFor(season);
  const sel = document.getElementById('tier-' + task + '-' + season);
  const max_tier = sel ? parseInt(sel.value, 10) : (window._defaultTiers[task] != null ? window._defaultTiers[task] : 7);
  const tierLabel = sel ? sel.options[sel.selectedIndex].text : 'auto';
  window.log('info', '\u25b6 season=' + season + '  task=' + task + '  force=' + force + '  tier\u2264' + max_tier + ' (' + tierLabel + ')');
  const d = await fetchJSON('/admin/api/index', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ season, task, force: !!force, max_tier }),
  });
  if (!d) { window.log('error', 'Rejected: index request failed'); return; }
  window.log('info', 'Job ' + d.job_id + ' queued \u2014 ' + d.label);
  window.registerJob(d);
}
async function triggerIndexEvents(season) {
  const force = forceFor(season);
  const sel = document.getElementById('tier-events-' + season);
  const max_tier = sel ? parseInt(sel.value, 10) : 7;
  const tierLabel = sel ? sel.options[sel.selectedIndex].text : 'all';
  window.log('info', '\u25b6 season=' + season + '  task=events  force=' + force + '  tier\u2264' + max_tier + ' (' + tierLabel + ')');
  const d = await fetchJSON('/admin/api/index', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ season, task: 'events', force: !!force, max_tier }),
  });
  if (!d) { window.log('error', 'Rejected: index request failed'); return; }
  window.log('info', 'Job ' + d.job_id + ' queued \u2014 ' + d.label);
  window.registerJob(d);
}
const _LAYER_LABELS = {
  events: 'Game Events', games: 'Games', groups: 'League Groups',
  leagues: 'Leagues', player_stats: 'Player Statistics',
  players: 'Players (roster)', teams: 'Teams', clubs: 'Clubs', all: 'ALL data',
};
async function deleteLayer(season, layer) {
  const label = _LAYER_LABELS[layer] || layer;
  const year  = season + '/' + String(season + 1).slice(-2);
  if (!confirm('Delete ' + label + ' for season ' + year + '?\n\nThis cannot be undone.')) return;
  window.log('warn', '\ud83d\uddd1 Deleting ' + label + ' for season ' + year + '\u2026');
  const d = await fetchJSON('/admin/api/season/' + season + '?layer=' + layer, { method: 'DELETE' });
  if (!d) { window.log('error', 'Delete failed: request failed'); return; }
  const total = Object.values(d.deleted || {}).reduce(function(a, b) { return a + b; }, 0);
  window.log('info', '\u2713 Deleted ' + total + ' rows (' + Object.entries(d.deleted || {}).map(function(e) { return e[0] + ':' + e[1]; }).join(', ') + ')');
  await window.loadStats();
}

/* =======================================================
   Freeze / Unfreeze season
======================================================= */
async function freezeSeason(sid) {
  const year = sid + '/' + String(sid + 1).slice(-2);
  if (!confirm('Freeze season ' + year + '?\n\nThe scheduler will skip this season until it is unfrozen.')) return;
  const d = await fetchJSON('/admin/api/season/' + sid + '/freeze', { method: 'POST' });
  if (!d) { window.log('error', 'Failed: freeze request failed'); return; }
  window.log('ok', '\u2744 Season ' + year + ' frozen');
  window.loadStats();
}
async function unfreezeSeason(sid) {
  const year = sid + '/' + String(sid + 1).slice(-2);
  const d = await fetchJSON('/admin/api/season/' + sid + '/unfreeze', { method: 'POST' });
  if (!d) { window.log('error', 'Failed: unfreeze request failed'); return; }
  window.log('ok', '\u2b1c Season ' + year + ' unfrozen');
  window.loadStats();
}

/* =======================================================
   Purge seasons
======================================================= */
async function runPurge(forcePreview) {
  const seasonVal = document.getElementById('purge-season').value.trim();
  const mode      = document.getElementById('purge-mode').value;
  const dryRun    = forcePreview || document.getElementById('purge-dry-run').checked;

  if (!seasonVal || isNaN(parseInt(seasonVal, 10))) {
    window.log('error', 'Purge: please enter a valid season ID.');
    return;
  }
  const season = parseInt(seasonVal, 10);
  const modeLabels = {
    'exact': 'only ' + season,
    'older': 'all seasons < ' + season,
    'older-or-equal': 'all seasons \u2264 ' + season,
    'newer': 'all seasons > ' + season,
    'newer-or-equal': 'all seasons \u2265 ' + season,
  };

  if (!dryRun) {
    if (!confirm('\u26a0 PERMANENTLY DELETE all data for ' + modeLabels[mode] + '?\n\nThis cannot be undone. Consider running Preview first.')) return;
  }

  window.log(dryRun ? 'info' : 'warn', (dryRun ? '\ud83d\udd0d Previewing' : '\ud83d\uddd1 Purging') + ' ' + modeLabels[mode] + '\u2026');

  const d = await fetchJSON('/admin/api/purge', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ season, mode, dry_run: dryRun }),
  });
  if (!d) { window.log('error', 'Purge rejected: request failed'); return; }
  window.log('info', 'Job ' + d.job_id + ' queued \u2014 ' + d.label);
  window.registerJob(d);
}

function toggleEl(bodyId, chevId) {
  document.getElementById(bodyId).classList.toggle('open');
  document.getElementById(chevId).classList.toggle('open');
}

Object.assign(window, {
  toggleSeason, setCurrentSeason, triggerIndex,
  triggerIndexTiered, triggerIndexEvents, deleteLayer,
  pullSeasons, runPurge, toggleEl,
  freezeSeason, unfreezeSeason,
});
