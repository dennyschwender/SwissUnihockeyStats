// backend/static/js/admin/database.js
import { fetchJSON, formatBytes } from './utils.js';

/* ── DB-specific log (writes to #db-log-box) ─────────────────────────────── */
function dbLog(level, msg) {
  const box = document.getElementById('db-log-box');
  if (!box) { window.log(level, msg); return; }
  if (box.textContent === 'Ready.') box.textContent = '';
  const line = document.createElement('div');
  line.className = level;
  line.textContent = `[${new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false})}] ${msg}`;
  box.appendChild(line);
  if (box.children.length > 200) box.removeChild(box.firstChild);
  box.scrollTop = box.scrollHeight;
}

function clearDbLog() {
  const box = document.getElementById('db-log-box');
  if (box) box.innerHTML = '';
}

/* ── DB info ─────────────────────────────────────────────────────────────── */
async function loadDbInfo() {
  const d = await fetchJSON('/admin/api/db-info');
  if (!d) return;

  const files  = d.files  || {};
  const pragma = d.pragma || {};

  // Totals chip — sum of db + wal
  const totalBytes = (files.db?.size || 0) + (files.wal?.size || 0);
  document.getElementById('t-db-size').textContent = formatBytes(totalBytes);

  // File sizes table
  const fileRows = [
    ['Main (.db)',     files.db],
    ['WAL (.db-wal)',  files.wal],
    ['SHM (.db-shm)', files.shm],
  ].map(([label, f]) => {
    if (!f) return '';
    const color = !f.exists ? '#6e7681' : f.size > 10 * 1024 * 1024 ? '#d29922' : '#3fb950';
    return `<tr>
      <td style="padding:3px 6px 3px 0;color:#8b949e">${label}</td>
      <td style="padding:3px 0;color:${color};font-variant-numeric:tabular-nums">${f.exists ? formatBytes(f.size) : '—'}</td>
    </tr>`;
  }).join('');
  document.getElementById('db-files-tbody').innerHTML = fileRows;

  // PRAGMA table
  const pages     = pragma.page_count   || 0;
  const freePages = pragma.freelist_count || 0;
  const pagesUsed = pages > 0 ? Math.round((1 - freePages / pages) * 100) : 100;
  const fmt       = n => (n == null ? '—' : Number(n).toLocaleString('de-CH'));
  const rows = [
    ['Pages',               `${fmt(pages)} (${fmt(freePages)} free)`],
    ['Page size',           pragma.page_size ? formatBytes(pragma.page_size) : '—'],
    ['Usage',               `${pagesUsed}%`],
    ['Journal mode',        pragma.journal_mode || '—'],
    ['WAL autocheckpoint',  pragma.wal_checkpoint != null ? `${pragma.wal_checkpoint} pages` : '—'],
  ].map(([k, v]) => `<tr>
    <td style="padding:3px 6px 3px 0;color:#8b949e;white-space:nowrap">${k}</td>
    <td style="padding:3px 0;font-variant-numeric:tabular-nums">${v}</td>
  </tr>`).join('');
  document.getElementById('db-pragma-tbody').innerHTML = rows;
}

/* ── VACUUM ──────────────────────────────────────────────────────────────── */
async function runVacuum() {
  const btn = document.getElementById('vacuum-btn');
  btn.disabled = true;
  btn.textContent = '⏳ Running…';
  dbLog('info', '🧹 VACUUM + WAL checkpoint started…');
  try {
    const d = await fetchJSON('/admin/api/vacuum', { method: 'POST' });
    if (d && d.ok && d.started) {
      dbLog('info', '⏳ VACUUM running in background — check server logs for completion (may take a few minutes).');
    } else if (d && d.ok) {
      dbLog('ok', `✓ VACUUM complete in ${d.elapsed_s}s`);
      await loadDbInfo();
    } else {
      dbLog('error', 'VACUUM failed: ' + (d?.detail || JSON.stringify(d)));
    }
  } catch(e) {
    dbLog('error', 'VACUUM error: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = '🧹 VACUUM + Checkpoint';
  }
}

/* ── Cleanup duplicates ──────────────────────────────────────────────────── */
async function runCleanup() {
  const btn = document.getElementById('cleanup-btn');
  btn.disabled = true;
  btn.textContent = '⏳ Running…';
  dbLog('info', '🗑️ Cleanup duplicates started…');
  try {
    const d = await fetchJSON('/admin/api/cleanup', { method: 'POST' });
    if (d && d.ok) {
      dbLog('ok',
        `✓ Cleanup done in ${d.elapsed_s}s — removed: ` +
        `${d.league_groups} league_group dups, ` +
        `${d.game_events} game_event dups, ` +
        `${d.sync_status} stale sync_status rows ` +
        `(total: ${d.total})`);
      await window.loadStats();
    } else if (d && d.conflict) {
      dbLog('warn', '⚠ ' + d.detail + ' — wait for jobs to finish first.');
    } else {
      dbLog('error', 'Cleanup failed: ' + (d?.detail || JSON.stringify(d)));
    }
  } catch(e) {
    dbLog('error', 'Cleanup error: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = '🗑️ Cleanup Duplicates';
  }
}

/* ── HTML escape helper ──────────────────────────────────────────────────── */
function esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

/* ── Sync Failures ───────────────────────────────────────────────────────── */
async function loadSyncFailures() {
  const el = document.getElementById('sf-content');
  const badge = document.getElementById('sf-count-badge');
  if (el) el.innerHTML = '<span style="color:#8b949e">Loading…</span>';
  const d = await fetchJSON('/admin/api/sync-failures');
  if (!d) { if (el) el.innerHTML = '<span style="color:#f85149">Failed to load.</span>'; return; }
  const failures = d.failures || [];
  if (badge) badge.innerHTML = failures.length
    ? `<span class="s-chip warn">${failures.length}</span>`
    : '';
  if (!failures.length) {
    if (el) el.innerHTML = '<span style="color:#3fb950">✓ No sync failures.</span>';
    return;
  }
  const rows = failures.map(f => {
    const retryBtn = (!f.can_retry && !f.retried_at)
      ? `<button class="btn btn-sm" onclick="retrySyncFailure(${esc(f.failure_id)})">Queue Retry</button>`
      : '—';
    return `<tr>
      <td style="padding:3px 8px 3px 0">${esc(f.game_api_id)}</td>
      <td style="padding:3px 8px 3px 0">${esc(f.season_id)}</td>
      <td style="padding:3px 8px 3px 0">${esc(f.game_date || '—')}</td>
      <td style="padding:3px 8px 3px 0">${esc(f.abandoned_at || '—')}</td>
      <td style="padding:3px 8px 3px 0">${esc((f.missing_fields || []).join(', ') || '—')}</td>
      <td style="padding:3px 8px 3px 0">${f.can_retry ? 'Yes' : 'No'}</td>
      <td style="padding:3px 8px 3px 0">${esc(f.retried_at || '—')}</td>
      <td style="padding:3px 0">${retryBtn}</td>
    </tr>`;
  }).join('');
  if (el) el.innerHTML = `<table style="width:100%;border-collapse:collapse;font-size:.8rem">
    <thead><tr style="color:#8b949e;border-bottom:1px solid #30363d">
      <th style="padding:3px 8px 3px 0;text-align:left">Game</th>
      <th style="padding:3px 8px 3px 0;text-align:left">Season</th>
      <th style="padding:3px 8px 3px 0;text-align:left">Date</th>
      <th style="padding:3px 8px 3px 0;text-align:left">Abandoned</th>
      <th style="padding:3px 8px 3px 0;text-align:left">Missing Fields</th>
      <th style="padding:3px 8px 3px 0;text-align:left">Can Retry</th>
      <th style="padding:3px 8px 3px 0;text-align:left">Retried At</th>
      <th style="padding:3px 0;text-align:left">Action</th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

async function retrySyncFailure(failureId) {
  const d = await fetchJSON(`/admin/api/sync-failures/${failureId}/retry`, { method: 'POST' });
  if (d && d.ok) { dbLog('ok', `✓ Failure #${failureId} queued for retry`); loadSyncFailures(); }
  else dbLog('error', `Failed to queue retry for #${failureId}`);
}

/* ── Unresolved Events ───────────────────────────────────────────────────── */
async function loadUnresolvedEvents() {
  const el = document.getElementById('ue-content');
  const badge = document.getElementById('ue-count-badge');
  if (el) el.innerHTML = '<span style="color:#8b949e">Loading…</span>';
  const d = await fetchJSON('/admin/api/unresolved-events');
  if (!d) { if (el) el.innerHTML = '<span style="color:#f85149">Failed to load.</span>'; return; }
  const events = d.events || [];
  if (badge) badge.innerHTML = events.length
    ? `<span class="s-chip warn">${events.length}</span>`
    : '';
  if (!events.length) {
    if (el) el.innerHTML = '<span style="color:#3fb950">✓ No unresolved events.</span>';
    return;
  }
  const rows = events.map(e => `<tr>
    <td style="padding:3px 8px 3px 0">${esc(e.raw_name)}</td>
    <td style="padding:3px 8px 3px 0">${esc(e.event_type)}</td>
    <td style="padding:3px 8px 3px 0">${esc(e.game_id)}</td>
    <td style="padding:3px 8px 3px 0">${esc(e.team_id)}</td>
    <td style="padding:3px 8px 3px 0">${esc(e.created_at || '—')}</td>
    <td style="padding:3px 0"><button class="btn btn-sm" onclick="dismissUnresolvedEvent(${esc(e.id)})">Dismiss</button></td>
  </tr>`).join('');
  if (el) el.innerHTML = `<p style="font-size:.78rem;color:#8b949e;margin:0 0 .5rem">
    These penalty events could not be matched to a player in the lineup and are excluded from PlayerStatistics.
  </p>
  <table style="width:100%;border-collapse:collapse;font-size:.8rem">
    <thead><tr style="color:#8b949e;border-bottom:1px solid #30363d">
      <th style="padding:3px 8px 3px 0;text-align:left">Name in event</th>
      <th style="padding:3px 8px 3px 0;text-align:left">Event type</th>
      <th style="padding:3px 8px 3px 0;text-align:left">Game ID</th>
      <th style="padding:3px 8px 3px 0;text-align:left">Team ID</th>
      <th style="padding:3px 8px 3px 0;text-align:left">Created</th>
      <th style="padding:3px 0;text-align:left">Action</th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

async function dismissUnresolvedEvent(eventId) {
  const d = await fetchJSON(`/admin/api/unresolved-events/${eventId}/dismiss`, { method: 'POST' });
  if (d && d.ok) { dbLog('ok', `✓ Event #${eventId} dismissed`); loadUnresolvedEvents(); }
  else dbLog('error', `Failed to dismiss event #${eventId}`);
}

Object.assign(window, {
  runVacuum, runCleanup, clearDbLog, loadDbInfo,
  loadSyncFailures, retrySyncFailure,
  loadUnresolvedEvents, dismissUnresolvedEvent,
});
export { loadDbInfo };
