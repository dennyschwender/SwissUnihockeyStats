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
    if (d && d.ok) {
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

Object.assign(window, { runVacuum, runCleanup, clearDbLog, loadDbInfo });
export { loadDbInfo };
