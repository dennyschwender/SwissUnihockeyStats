// backend/static/js/admin/settings.js
import { fetchJSON } from './utils.js';

/* ── Scheduler season filter + max concurrent ─────────────────────────────── */

function schedMarkDirty() { window._settingsDirty = true; }

async function schedSaveFilter() {
  const rawMin = document.getElementById('sched-min-season').value.trim();
  const rawExc = document.getElementById('sched-excluded').value.trim();
  const rawMax = document.getElementById('sched-max-concurrent').value.trim();
  const rawWorkers = document.getElementById('sched-player-game-stats-workers').value.trim();
  const min_season = rawMin ? parseInt(rawMin, 10) : null;
  const excluded_seasons = rawExc
    ? rawExc.split(',').map(s => s.trim()).filter(Boolean).map(Number).filter(n => !isNaN(n))
    : [];
  const max_concurrent = rawMax ? Math.max(1, parseInt(rawMax, 10)) : 2;
  const player_game_stats_workers = rawWorkers ? Math.max(1, parseInt(rawWorkers, 10)) : 10;

  // Save season filter
  const d1 = await fetchJSON('/admin/api/scheduler', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({action: 'season_filter', min_season, excluded_seasons}),
  });
  // Save max_concurrent
  const d2 = await fetchJSON('/admin/api/scheduler', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({action: 'max_concurrent', value: max_concurrent}),
  });
  // Save player_game_stats_workers
  const d3 = await fetchJSON('/admin/api/scheduler', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({action: 'player_game_stats_workers', value: player_game_stats_workers}),
  });
  if (d1 && d2 && d3) {
    window._settingsDirty = false;
    window.log('info', `✓ Scheduler settings saved — min: ${min_season ?? 'none'}, excluded: ${excluded_seasons.join(', ') || 'none'}, max concurrent: ${max_concurrent}, API workers: ${player_game_stats_workers}`);
    await window.loadScheduler();
  } else {
    window.log('error', 'Failed to save scheduler settings');
  }
}

async function schedClearFilter() {
  await fetchJSON('/admin/api/scheduler', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({action: 'season_filter', min_season: null, excluded_seasons: []}),
  });
  await fetchJSON('/admin/api/scheduler', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({action: 'max_concurrent', value: 2}),
  });
  await fetchJSON('/admin/api/scheduler', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({action: 'player_game_stats_workers', value: 10}),
  });
  window._settingsDirty = false;
  window.log('info', '✓ Scheduler settings cleared (max concurrent reset to 2, API workers reset to 10)');
  await window.loadScheduler();
}

/* ── Rendering filters ───────────────────────────────────────────────────── */
let _rfDirty = false;
function rfMarkDirty() { _rfDirty = true; }

function _parseList(raw) {
  return raw.split(',').map(s => s.trim()).filter(Boolean);
}
function _parseIntList(raw) {
  return _parseList(raw).map(Number).filter(n => !isNaN(n));
}

async function loadRenderingFilters() {
  const d = await fetchJSON('/admin/api/rendering');
  if (!d) return;
  if (_rfDirty) return; // don't overwrite unsaved edits
  const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = (val||[]).join(', '); };
  setVal('rf-lg-names',   d.excluded_league_names);
  setVal('rf-lg-ids',     d.excluded_league_ids);
  setVal('rf-club-names', d.excluded_club_names);
  setVal('rf-club-ids',   d.excluded_club_ids);
  setVal('rf-team-names', d.excluded_team_names);
  setVal('rf-team-ids',   d.excluded_team_ids);
}

async function rfSave() {
  const payload = {
    excluded_league_names:  _parseList(document.getElementById('rf-lg-names').value),
    excluded_league_ids:    _parseIntList(document.getElementById('rf-lg-ids').value),
    excluded_club_names:    _parseList(document.getElementById('rf-club-names').value),
    excluded_club_ids:      _parseIntList(document.getElementById('rf-club-ids').value),
    excluded_team_names:    _parseList(document.getElementById('rf-team-names').value),
    excluded_team_ids:      _parseIntList(document.getElementById('rf-team-ids').value),
  };
  const d = await fetchJSON('/admin/api/rendering', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify(payload),
  });
  if (d) {
    _rfDirty = false;
    window.log('info', '✓ Rendering filters saved');
    await loadRenderingFilters();
  } else {
    window.log('error', 'Failed to save rendering filters');
  }
}

async function rfClear() {
  const empty = { excluded_league_names:[], excluded_league_ids:[], excluded_club_names:[], excluded_club_ids:[], excluded_team_names:[], excluded_team_ids:[] };
  const d = await fetchJSON('/admin/api/rendering', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify(empty),
  });
  if (d) {
    _rfDirty = false;
    window.log('info', '✓ Rendering filters cleared');
    await loadRenderingFilters();
  } else {
    window.log('error', 'Failed to clear rendering filters');
  }
}

/* ── Policy tier limits ──────────────────────────────────────────────────── */
async function schedSaveTiers() {
  const tiersBodyEl = document.getElementById('sched-tiers-tbody');
  if (!tiersBodyEl) return;
  const tiers = {};
  tiersBodyEl.querySelectorAll('select').forEach(sel => {
    const name = sel.id.replace('tier-', '');
    tiers[name] = parseInt(sel.value, 10);
  });
  const d = await fetchJSON('/admin/api/scheduler', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({action: 'policy_tiers', tiers}),
  });
  if (d) {
    window._settingsDirty = false;
    window.log('info', '✓ Policy tier limits saved');
    await window.loadScheduler();
  } else {
    window.log('error', 'Failed to save tier limits');
  }
}

Object.assign(window, {
  schedSaveFilter, schedClearFilter, schedSaveTiers,
  rfMarkDirty, rfSave, rfClear, schedMarkDirty,
});
export { loadRenderingFilters };
