// backend/static/js/admin/scheduling.js
import { fetchJSON } from './utils.js';

/* =======================================================
   Shared state
======================================================= */
window.jobs = window.jobs || {};  // job_id -> job object
let _activitySyncRows = [];   // last sync_status snapshot (DB-backed)
let _activityHistRows = [];   // last scheduler history snapshot (in-memory)

const _pollErrors = {};  // job_id -> consecutive error count
const _seenJobHistory = new Set(); // job_ids whose history has been shown in the log
const POLL_MAX_ERRORS = 4;
const JOB_KEEP_MS = 5 * 60 * 1000;  // keep finished job cards visible for 5 minutes

// _activitySyncRows is written by stats.js via window._activitySyncRows
Object.defineProperty(window, '_activitySyncRows', {
  get() { return _activitySyncRows; },
  set(v) { _activitySyncRows = v; },
  configurable: true,
});

/* =======================================================
   Job registration + polling
======================================================= */
function registerJob(data) {
  const startedAt = data.started_at ? new Date(data.started_at).getTime() : Date.now();
  window.jobs[data.job_id] = { ...data, status: 'running', progress: 0, startedAt };
  renderJobs();
  setTimeout(() => pollJob(data.job_id), 1200);
}

async function pollJob(job_id) {
  try {
    const r = await fetch('/admin/api/jobs/' + job_id);

    // 404 = server restarted and lost in-memory state -> job is dead
    if (r.status === 404) {
      _markJobFailed(job_id, 'Job lost -- server may have restarted');
      return;
    }
    if (!r.ok) {
      _handlePollError(job_id, 'HTTP ' + r.status);
      return;
    }

    _pollErrors[job_id] = 0;  // reset error counter on success
    const d = await r.json();

    // Derive startedAt from the server-sent ISO timestamp (survives page refresh)
    if (d.started_at)
      d.startedAt = new Date(d.started_at).getTime();
    else if (window.jobs[job_id] && window.jobs[job_id].startedAt)
      d.startedAt = window.jobs[job_id].startedAt;
    else if (d.status === 'running')
      d.startedAt = Date.now();

    // On first encounter of a job (e.g. after page refresh), replay the
    // full output history so the log isn't blank for an already-running job.
    if (!_seenJobHistory.has(job_id)) {
      _seenJobHistory.add(job_id);
      (d.log_history || []).forEach(l =>
        window.log(l.level || 'info', '[' + job_id.slice(-6) + '] ' + l.msg)
      );
    }
    (d.log_lines || []).forEach(l =>
      window.log(l.level || 'info', '[' + job_id.slice(-6) + '] ' + l.msg)
    );
    window.jobs[job_id] = { ...d, log_lines: [], log_history: [] };
    renderJobs();

    if (d.status === 'running') {
      setTimeout(() => pollJob(job_id), 1500);
    } else if (d.status === 'done') {
      const stats = Object.entries(d.stats || {}).map(([k,v]) => k + ':' + window.fmt(v)).join(' ');
      window.log('ok', '\u2713 Job ' + job_id.slice(-6) + ' done  ' + stats);
      setTimeout(window.loadStats, 600);
      setTimeout(() => { delete window.jobs[job_id]; _seenJobHistory.delete(job_id); renderJobs(); }, JOB_KEEP_MS);
    } else if (d.status === 'stopped') {
      window.log('warn', '\u25a0 Job ' + job_id.slice(-6) + ' stopped');
      setTimeout(() => { delete window.jobs[job_id]; _seenJobHistory.delete(job_id); renderJobs(); }, JOB_KEEP_MS);
    } else if (d.status === 'error') {
      window.log('error', '\u2717 Job ' + job_id.slice(-6) + ' failed: ' + d.error);
      setTimeout(() => { delete window.jobs[job_id]; _seenJobHistory.delete(job_id); renderJobs(); }, JOB_KEEP_MS);
    }
  } catch(e) {
    _handlePollError(job_id, e.message);
  }
}

function _handlePollError(job_id, msg) {
  const n = (_pollErrors[job_id] || 0) + 1;
  _pollErrors[job_id] = n;
  if (n >= POLL_MAX_ERRORS) {
    _markJobFailed(job_id, 'Lost contact after ' + n + ' attempts (' + msg + ')');
  } else {
    window.log('warn', '[' + job_id.slice(-6) + '] Poll error (' + n + '/' + POLL_MAX_ERRORS + '): ' + msg);
    setTimeout(() => pollJob(job_id), 3000 * n);  // exponential back-off
  }
}

function _markJobFailed(job_id, reason) {
  window.log('error', '\u2717 Job ' + job_id.slice(-6) + ' failed: ' + reason);
  if (window.jobs[job_id]) {
    window.jobs[job_id].status = 'error';
    window.jobs[job_id].error  = reason;
  }
  delete _pollErrors[job_id];
  renderJobs();
}

/* =======================================================
   Jobs panel
======================================================= */
function renderJobs() {
  const c = document.getElementById('jobs-container');
  const arr = Object.values(window.jobs);
  if (!arr.length) { c.textContent = ''; c.innerHTML = '<div class="no-jobs">No jobs yet.</div>'; return; }

  c.innerHTML = [...arr].reverse().map(j => {
    const st  = j.status || 'running';
    const pct = j.progress ?? 0;
    const pulseC  = st === 'running' ? ' pulse' : '';
    const stopBtn = st === 'running'
      ? '<button class="btn btn-sm" style="color:#f85149;border-color:#da3633" onclick="stopJob(\'' + j.job_id + '\')">&#9632; Stop</button>'
      : '';
    const stats = j.stats ? Object.entries(j.stats).map(([k,v]) => k + ':' + window.fmt(v)).join(' ') : '';
    let errorRow = '';
    if ((st === 'error' || st === 'stopped') && j.error) {
      const lines = j.error.split('\n');
      const summary = _esc(lines[0]);
      const full    = _esc(j.error);
      const eid     = 'err-' + j.job_id;
      errorRow = '<div style="margin-top:.3rem;font-size:.72rem;color:#f85149"><span>\u26a0 ' + summary + '</span>';
      if (lines.length > 1) {
        errorRow += '<span style="cursor:pointer;color:#8b949e;margin-left:.4rem" onclick="const el=document.getElementById(\'' + eid + '\');el.style.display=el.style.display===\'none\'?\'block\':\'none\'">&#9658; details</span>'
          + '<pre id="' + eid + '" style="display:none;margin:.3rem 0 0;background:#161b22;border:1px solid #30363d;border-radius:4px;padding:.4rem .6rem;font-size:.68rem;color:#cdd9e5;overflow-x:auto;white-space:pre-wrap;word-break:break-all">' + full + '</pre>';
      }
      errorRow += '</div>';
    }
    const statsRow = st === 'done' && stats
      ? '<div style="margin-top:.2rem;font-size:.7rem;color:#8b949e">' + stats + '</div>'
      : '';
    const elapsedSpan = st === 'running'
      ? '<span class="job-elapsed" id="elapsed-' + j.job_id + '" style="font-size:.7rem;color:#6e7681;margin-left:auto;margin-right:.4rem;white-space:nowrap;font-variant-numeric:tabular-nums">' + _fmtElapsed(j.startedAt) + '</span>'
      : '';
    const pctSpan = st === 'running'
      ? '<span style="font-size:.7rem;color:#8b949e;white-space:nowrap;min-width:2.4rem;text-align:right">' + pct + '%</span>'
      : '';
    return '<div class="job-item">'
      + '<div class="job-item-top">'
      + '<span class="job-tag ' + st + pulseC + '">' + st + '</span>'
      + '<span class="job-label">' + (j.label || j.task || '\u2014') + '</span>'
      + '<span class="job-season">' + (j.season ? 'S' + j.season : '') + '</span>'
      + elapsedSpan + stopBtn
      + '</div>'
      + '<div style="display:flex;align-items:center;gap:.5rem;">'
      + '<div class="progress-wrap" style="flex:1"><div class="progress-bar" style="width:' + pct + '%"></div></div>'
      + pctSpan
      + '</div>'
      + errorRow + statsRow
      + '</div>';
  }).join('');
}

/* =======================================================
   Running-clock helpers
======================================================= */
function _fmtElapsed(startedAt) {
  if (!startedAt) return '';
  const s = Math.floor((Date.now() - startedAt) / 1000);
  if (s < 0) return '0s';
  if (s < 60) return s + 's';
  const m = Math.floor(s / 60), rs = s % 60;
  if (m < 60) return m + 'm ' + String(rs).padStart(2,'0') + 's';
  const h = Math.floor(m / 60), rm = m % 60;
  return h + 'h ' + String(rm).padStart(2,'0') + 'm ' + String(rs).padStart(2,'0') + 's';
}

// Tick every second -- just update the text of existing elapsed spans,
// no full re-render needed.
setInterval(() => {
  for (const [id, j] of Object.entries(window.jobs)) {
    if (j.status !== 'running' || !j.startedAt) continue;
    const el = document.getElementById('elapsed-' + id);
    if (el) el.textContent = _fmtElapsed(j.startedAt);
  }
}, 1000);

async function clearDoneJobs() {
  // Remove finished entries from server history so they don't come back on the next poll
  await fetchJSON('/admin/api/scheduler', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({action: 'clear_done'})
  });
  // Also clear locally from the active jobs panel
  for (const id in window.jobs) {
    if (window.jobs[id].status !== 'running') {
      delete window.jobs[id];
      _seenJobHistory.delete(id);
    }
  }
  renderJobs();
}

async function stopJob(job_id) {
  const d = await fetchJSON('/admin/api/jobs/' + job_id, { method: 'DELETE' });
  if (!d) return;
  if (d.ok) {
    window.log('warn', '\u25a0 Job ' + job_id + ' stopped');
    if (window.jobs[job_id]) window.jobs[job_id].status = 'stopped';
    renderJobs();
  } else {
    window.log('warn', d.detail || 'Stop failed');
  }
}

/* =======================================================
   Unified Activity Table  (jobs + sync_status merged)
======================================================= */
function renderActivityTable() {
  const tbody = document.getElementById('activity-tbody');
  if (!tbody) return;

  // Normalise scheduler-history rows
  const jobRows = _activityHistRows.slice(0, 50).map(h => {
    const statsStr = h.stats
      ? Object.entries(h.stats).map(([k, v]) => k + ':' + window.fmt(v)).join(' ')
      : '';
    return {
      isJob:   true,
      kind:    'job',
      detail:  h.policy + ' / ' + h.task,
      season:  h.season || '\u2014',
      status:  h.status,
      timeTxt: h.finished_at || h.scheduled_at || '',
      timeRaw: h.finished_at || h.scheduled_at || '',
      records: statsStr || '\u2014',
      error:   h.error || null,
    };
  });

  // Normalise sync_status rows
  const syncRows = _activitySyncRows.map(s => ({
    isJob:   false,
    kind:    s.entity_type,
    detail:  s.entity_id,
    season:  '\u2014',
    status:  s.status,
    timeTxt: s.last_sync || '',
    timeRaw: s.last_sync || '',
    records: s.records != null ? window.fmt(s.records) : '\u2014',
    error:   s.error || null,
  }));

  // Merge and sort newest-first
  const all = [...jobRows, ...syncRows].sort((a, b) => {
    if (!a.timeRaw && !b.timeRaw) return 0;
    if (!a.timeRaw) return 1;
    if (!b.timeRaw) return -1;
    return b.timeRaw.localeCompare(a.timeRaw);
  }).slice(0, 150);

  if (!all.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="padding:.75rem 1rem;color:#6e7681;text-align:center">No activity yet.</td></tr>';
    return;
  }

  tbody.innerHTML = all.map(r => {
    const cls = (r.status === 'done' || r.status === 'completed') ? 's-ok'
              : (r.status === 'error' || r.status === 'failed')   ? 's-fail'
              : 's-prog';
    const kindBadge = r.isJob
      ? '<span style="font-size:.65rem;background:#1f6feb33;color:#58a6ff;padding:1px 5px;border-radius:3px;white-space:nowrap">\u26a1 job</span>'
      : '<span style="font-size:.65rem;background:#161b22;color:#8b949e;padding:1px 5px;border-radius:3px;white-space:nowrap">' + r.kind + '</span>';
    const detailCell = r.isJob
      ? '<span style="font-size:.72rem">' + r.detail + '</span>'
      : '<span style="font-family:monospace;font-size:.65rem;max-width:160px;display:inline-block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + _esc(r.detail) + '">' + r.detail + '</span>';
    const errHtml = r.error
      ? '<span title="' + _esc(r.error) + '" class="s-fail" style="cursor:help;font-size:.68rem">\u26a0 ' + _esc(r.error).slice(0, 40) + (r.error.length > 40 ? '\u2026' : '') + '</span>'
      : '\u2014';
    return '<tr>'
      + '<td>' + kindBadge + '</td>'
      + '<td>' + detailCell + '</td>'
      + '<td>' + r.season + '</td>'
      + '<td class="' + cls + '">' + r.status + '</td>'
      + '<td style="color:#6e7681;white-space:nowrap">' + (r.timeTxt || '\u2014') + '</td>'
      + '<td style="font-size:.72rem">' + r.records + '</td>'
      + '<td>' + errHtml + '</td>'
      + '</tr>';
  }).join('');
}

/* =======================================================
   Scheduler panel
======================================================= */
async function loadScheduler() {
  try {
    const [schedResp, jobsResp] = await Promise.all([
      fetch('/admin/api/scheduler'),
      fetch('/admin/api/jobs'),
    ]);
    if (schedResp.ok) {
      const d = await schedResp.json();
      renderScheduler(d);
      // Pick up scheduler-launched jobs not yet tracked in the active jobs panel
      (d.history || []).forEach(h => {
        if (!window.jobs[h.job_id]) {
          const isRunning = h.status === 'running' || h.status === 'pending';
          const startedAt = h.started_at ? new Date(h.started_at).getTime() : (isRunning ? Date.now() : undefined);
          window.jobs[h.job_id] = { job_id: h.job_id, label: h.policy + (h.season ? ' S' + h.season : ''), season: h.season, task: h.task, status: isRunning ? 'running' : h.status, progress: isRunning ? 0 : 100, startedAt };
          renderJobs();
          if (isRunning) pollJob(h.job_id);
        }
      });
    }
    // Pick up manually-triggered jobs (survive page refresh)
    if (jobsResp.ok) {
      const manualJobs = await jobsResp.json();
      manualJobs.forEach(j => {
        if (!window.jobs[j.job_id]) {
          const startedAt = j.started_at ? new Date(j.started_at).getTime() : (j.status === 'running' ? Date.now() : undefined);
          window.jobs[j.job_id] = { ...j, startedAt };
          renderJobs();
          if (j.status === 'running') {
            pollJob(j.job_id);
          } else if (['done', 'error', 'stopped'].includes(j.status)) {
            setTimeout(() => { delete window.jobs[j.job_id]; renderJobs(); }, 60000);
          }
        }
      });
    }
  } catch(e) { /* scheduler may not yet be running */ }
}

function renderScheduler(d) {
  const badge      = document.getElementById('sched-badge');
  const statusTxt  = document.getElementById('sched-status-txt');
  const enableBtn  = document.getElementById('sched-enable-btn');
  const disableBtn = document.getElementById('sched-disable-btn');

  if (d.enabled) {
    badge.className   = 's-chip ok';
    badge.textContent = 'enabled';
    enableBtn.disabled  = true;
    disableBtn.disabled = false;
    const running = d.running ?? 0;
    const maxC    = (d.season_filter || {}).max_concurrent ?? 2;
    statusTxt.textContent = d.queue.length + ' queued \u00b7 ' + running + '/' + maxC + ' running';
  } else {
    badge.className   = 's-chip empty';
    badge.textContent = 'disabled';
    enableBtn.disabled  = false;
    disableBtn.disabled = true;
    statusTxt.textContent = 'scheduler paused';
  }

  // Season filter inputs + policy tier table -- skip if user has unsaved edits
  if (!window._settingsDirty) {
    const sf = d.season_filter || {};
    const minEl = document.getElementById('sched-min-season');
    const excEl = document.getElementById('sched-excluded');
    const maxEl = document.getElementById('sched-max-concurrent');
    if (minEl) minEl.value = sf.min_season != null ? sf.min_season : '';
    if (excEl) excEl.value = (sf.excluded_seasons || []).join(', ');
    if (maxEl) maxEl.value = sf.max_concurrent ?? 2;

    // Policy tier selects
    const TIER_LABELS = {
      1: 'T1 \u2014 NLA/L-UPL only',
      2: 'T2 \u2014 + NLB, U21A/U18A/U16A',
      3: 'T3 \u2014 + 1. Liga, U21B/U18B/U16B',
      4: 'T4 \u2014 + 2. Liga, U21C/U18C/U16C',
      5: 'T5 \u2014 + 3. Liga, U21D',
      6: 'T6 \u2014 All (+ 4./5. Liga, Regional, Cups)',
    };
    const tiersBodyEl = document.getElementById('sched-tiers-tbody');
    if (tiersBodyEl && d.policy_tiers) {
      // Sync manual tier dropdowns from policy config
      const _policyMap = {
        clubs:             d.policy_tiers.clubs,
        teams:             d.policy_tiers.teams,
        events:            d.policy_tiers.game_events,
        players:           d.policy_tiers.players,
        player_stats:      d.policy_tiers.player_stats,
        game_lineups:      d.policy_tiers.game_lineups      || 3,
        player_game_stats: d.policy_tiers.player_game_stats || 3,
        leagues:           d.policy_tiers.leagues,
        groups:            d.policy_tiers.league_groups     || 5,
        games:             d.policy_tiers.games             || 3,
      };
      for (const [task, tier] of Object.entries(_policyMap)) {
        if (!tier) continue;
        window._defaultTiers[task] = tier;
        const attr = task === 'events' ? '[id^="tier-events-"]' : '[id^="tier-' + task + '-"]';
        document.querySelectorAll('.tier-select' + attr).forEach(el => { el.value = tier; });
      }
      tiersBodyEl.innerHTML = Object.entries(d.policy_tiers).map(([name, tier]) => {
        const opts = Object.entries(TIER_LABELS).map(([v, lbl]) =>
          '<option value="' + v + '"' + (+v === tier ? ' selected' : '') + '>' + lbl + '</option>'
        ).join('');
        return '<tr>'
          + '<td style="padding:2px 8px;color:#e6edf3">' + name + '</td>'
          + '<td style="padding:2px 8px"><select id="tier-' + name + '" onchange="schedMarkDirty()"'
          + ' style="background:#161b22;border:1px solid #30363d;border-radius:4px;color:#e6edf3;padding:2px 4px;font-size:.75rem">' + opts + '</select></td>'
          + '</tr>';
      }).join('');
    }
  }

  // Queue
  const queueEl = document.getElementById('sched-queue');
  if (!d.queue.length) {
    queueEl.innerHTML = '<div style="padding:.5rem 1rem;font-size:.75rem;color:#6e7681">Queue empty.</div>';
  } else {
    queueEl.innerHTML = d.queue.map(j => {
      const seasonPill = j.season
        ? '<span class="count-pill has-data">S' + j.season + '</span>'
        : '<span class="count-pill">global</span>';
      const runAtTitle = j.run_at.replace('T',' ').replace('Z',' UTC');
      return '<div class="task-row">'
        + '<span class="task-name">' + j.policy + '</span>'
        + '<div class="task-counts">'
        + seasonPill
        + '<span class="count-pill" title="' + runAtTitle + '">' + fmtRunAt(j.run_at) + '</span>'
        + '<span class="count-pill' + (j.due_in_s < 120 ? ' has-data' : '') + '" title="' + runAtTitle + '">' + fmtDue(j.due_in_s) + '</span>'
        + '</div>'
        + '<div class="task-btns">'
        + '<button class="btn btn-sm btn-orange" onclick="schedTrigger(\'' + j.policy + '\',' + (j.season||'null') + ')">&#9654; Now</button>'
        + '</div>'
        + '</div>';
    }).join('');
  }

  // History -> feed into combined activity table
  _activityHistRows = d.history || [];
  renderActivityTable();
}

async function schedSetEnabled(v) {
  const data = await fetchJSON('/admin/api/scheduler', {
    method:  'POST',
    headers: {'Content-Type':'application/json'},
    body:    JSON.stringify({action: v ? 'enable' : 'disable'}),
  });
  if (data) await loadScheduler();
}

async function schedTrigger(policy, season) {
  const d = await fetchJSON('/admin/api/scheduler', {
    method:  'POST',
    headers: {'Content-Type':'application/json'},
    body:    JSON.stringify({action:'trigger', policy, season}),
  });
  if (!d) return;
  if (d.ok) {
    window.log('info', '\u25b6 scheduler trigger: ' + policy + ' S' + season + '  job=' + d.job_id);
    // Register the newly-launched job in the active jobs panel and start polling
    if (d.job_id) {
      registerJob({ job_id: d.job_id, label: d.label || policy, season: d.season, task: d.task || policy });
    }
    setTimeout(loadScheduler, 800);
  } else {
    window.log('error', d.detail || 'Trigger failed');
  }
}

function fmtDue(secs) {
  if (secs <= 0)    return 'due now';
  if (secs < 60)    return secs + 's';
  if (secs < 3600)  return Math.round(secs/60) + 'm';
  if (secs < 86400) return Math.round(secs/3600) + 'h';
  return Math.round(secs/86400) + 'd';
}

function fmtRunAt(isoUtc) {
  if (!isoUtc) return '\u2014';
  const d = new Date(isoUtc);
  if (isNaN(d)) return isoUtc;
  const now = new Date();
  const diffMs = d - now;
  const diffDays = Math.floor(diffMs / 86400000);
  // Same calendar day -> just show time
  const timeFmt = {hour:'2-digit', minute:'2-digit', hour12: false};
  if (d.toDateString() === now.toDateString())
    return 'today ' + d.toLocaleTimeString([], timeFmt);
  // Tomorrow
  const tomorrow = new Date(now); tomorrow.setDate(tomorrow.getDate() + 1);
  if (d.toDateString() === tomorrow.toDateString())
    return 'tomorrow ' + d.toLocaleTimeString([], timeFmt);
  // Within 7 days -> weekday + time
  if (diffDays < 7)
    return d.toLocaleDateString([], {weekday:'short'}) + ' ' + d.toLocaleTimeString([], timeFmt);
  // Farther out -> date + time
  return d.toLocaleDateString([], {month:'short', day:'numeric'}) + ' ' + d.toLocaleTimeString([], timeFmt);
}

/* =======================================================
   Staleness Diagnostics
======================================================= */
async function loadSchedDiag() {
  const tbody  = document.getElementById('diag-tbody');
  const errEl  = document.getElementById('diag-error');
  tbody.innerHTML = '<tr><td colspan="6" style="padding:.75rem 1rem;color:#6e7681;text-align:center">Loading\u2026</td></tr>';
  errEl.style.display = 'none';
  try {
    const d = await fetchJSON('/admin/api/scheduler-diag');
    if (!d) { errEl.style.display=''; errEl.textContent='Request failed'; return; }
    if (!d.ok) { errEl.style.display=''; errEl.textContent=d.error||'unknown error'; return; }

    const rows = d.rows || [];
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="6" style="padding:.75rem 1rem;color:#6e7681;text-align:center">No data.</td></tr>';
      return;
    }

    // Count problems per policy for a summary header (FROZEN = intentional, not a problem)
    const problems = rows.filter(r => r.status !== 'FRESH' && r.status !== 'FROZEN');

    tbody.innerHTML = rows.map(r => {
      const isFresh    = r.status === 'FRESH';
      const isNever    = r.status === 'NEVER_SYNCED';
      const isFrozen   = r.status === 'FROZEN';
      const skipRow    = r.current_only && !r.is_current;

      const statusCls  = isFresh ? 's-ok' : (isNever ? 's-fail' : isFrozen ? '' : 's-warn');
      const statusLbl  = isNever ? '\u26a0 NEVER SYNCED' : isFrozen ? '\u2744 frozen' : r.status;
      const rowStyle   = skipRow ? 'opacity:.4;' : (isNever || r.status==='STALE' ? 'background:#1a0e0e;' : isFrozen ? 'opacity:.45;' : '');
      const seasonLbl  = r.season ? 'S' + r.season + (r.is_current ? ' \u2605' : '') : 'global';
      const skipNote   = skipRow ? ' <span style="color:#6e7681;font-size:.6rem">(past, skip)</span>' : '';
      const maxAgeLbl  = r.max_age_h >= 24 ? Math.round(r.max_age_h/24) + 'd' : r.max_age_h + 'h';
      return '<tr style="' + rowStyle + '">'
        + '<td style="font-size:.72rem">' + r.policy + '<br><span style="color:#6e7681;font-size:.6rem">' + r.entity_type + '</span></td>'
        + '<td>' + seasonLbl + skipNote + '</td>'
        + '<td style="white-space:nowrap;font-size:.72rem">' + (r.last_sync || '\u2014') + '</td>'
        + '<td>' + maxAgeLbl + '</td>'
        + '<td class="' + statusCls + '">' + statusLbl + '</td>'
        + '<td style="font-size:.72rem">' + r.next_run + '</td>'
        + '</tr>';
    }).join('');

    if (problems.length) {
      const neverCount = problems.filter(r => r.status === 'NEVER_SYNCED').length;
      const staleCount = problems.filter(r => r.status === 'STALE').length;
      errEl.style.display = '';
      errEl.style.color = '#d29922';
      errEl.textContent = '\u26a0 ' + problems.length + ' problem row(s): ' + neverCount + ' never-synced, ' + staleCount + ' stale -- these will fire on every scheduler tick.';
    }
  } catch(e) {
    errEl.style.display=''; errEl.textContent='Fetch error: '+e.message;
  }
}

/* =======================================================
   Private helpers
======================================================= */
function _esc(s) {
  return String(s || '')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

/* =======================================================
   Window exports + module exports
======================================================= */
Object.assign(window, {
  clearDoneJobs, stopJob, schedSetEnabled, loadSchedDiag,
  renderActivityTable, registerJob, schedTrigger,
});

export { loadScheduler, pollJob };
