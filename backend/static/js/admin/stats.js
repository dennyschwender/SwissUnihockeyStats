// backend/static/js/admin/stats.js
import { fetchJSON } from './utils.js';
import { renderSeasons, isSeasonFiltered, setFreshnessMap, setSeasonFilter, setCompletenessMap } from './seasons.js?v=2';

/* =======================================================
   loadStats  — fetches /admin/api/stats + scheduler-diag,
   updates the totals bar, and renders the seasons accordion.
======================================================= */
export async function loadStats() {
  try {
    const [statsR, diagR, complR] = await Promise.all([
      fetch('/admin/api/stats'),
      fetch('/admin/api/scheduler-diag').catch(function() { return null; }),
      fetch('/admin/api/seasons/completeness').catch(function() { return null; }),
    ]);
    if (!statsR.ok) throw new Error('HTTP ' + statsR.status);
    const d = await statsR.json();

    // Update freshness map + season filter (best-effort, don't block stats on failure)
    if (diagR && diagR.ok) {
      try {
        const diagD = await diagR.json();
        if (diagD.ok) {
          const freshnessMap = {};
          for (const row of diagD.rows || []) {
            if (row.season) freshnessMap[row.entity_type + ':' + row.season] = row;
          }
          setFreshnessMap(freshnessMap);
          if (diagD.season_filter) setSeasonFilter(diagD.season_filter);
        }
      } catch (_) {}
    }

    const t = d.totals || {};
    document.getElementById('t-seasons').textContent = window.fmt(t.seasons);
    document.getElementById('t-clubs'  ).textContent = window.fmt(t.clubs);
    document.getElementById('t-teams'  ).textContent = window.fmt(t.teams);
    document.getElementById('t-players').textContent = window.fmt(t.players);
    document.getElementById('t-tp'     ).textContent = window.fmt(t.team_players);
    document.getElementById('t-pstats' ).textContent = window.fmt(t.player_stats);
    document.getElementById('t-leagues').textContent = window.fmt(t.leagues);
    document.getElementById('t-groups' ).textContent = window.fmt(t.league_groups);
    document.getElementById('t-games'  ).textContent = window.fmt(t.games);
    document.getElementById('t-gp'     ).textContent = window.fmt(t.game_players);
    document.getElementById('t-events' ).textContent = window.fmt(t.game_events);

    // Load completeness data (best-effort)
    if (complR && complR.ok) {
      try {
        const complD = await complR.json();
        const complMap = {};
        for (const row of (Array.isArray(complD) ? complD : (complD.seasons || []))) complMap[row.season_id] = row;
        setCompletenessMap(complMap);
      } catch (_) {}
    }

    const visibleSeasons = (d.by_season || []).filter(function(s) { return !isSeasonFiltered(s.season_id); });
    renderSeasons(visibleSeasons);
    window._activitySyncRows = d.sync_status || [];
    window.renderActivityTable();

    document.getElementById('refresh-ts').textContent =
      'Updated ' + new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false});
  } catch(e) {
    window.log('error', 'Stats load failed: ' + e.message);
  }
}
