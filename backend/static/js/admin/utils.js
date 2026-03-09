// backend/static/js/admin/utils.js
// Shared utilities for all admin tab modules.

/**
 * Fetch JSON from url. Returns parsed JSON or null on error.
 * Shows a console.error on non-2xx responses.
 */
export async function fetchJSON(url, options = {}) {
  try {
    const r = await fetch(url, options);
    if (!r.ok) {
      console.error(`fetchJSON ${url}: HTTP ${r.status}`);
      return null;
    }
    return await r.json();
  } catch (e) {
    console.error(`fetchJSON ${url}:`, e);
    return null;
  }
}

/**
 * Poll fn every intervalMs. Pauses when browser tab is hidden.
 * Returns handle with .stop() method.
 */
export function poll(fn, intervalMs) {
  let id = null;
  const tick = () => { if (!document.hidden) fn(); };
  const start = () => { id = setInterval(tick, intervalMs); };
  const stop  = () => { if (id !== null) { clearInterval(id); id = null; } };
  document.addEventListener('visibilitychange', () => document.hidden ? stop() : start());
  start();
  return { stop };
}

/**
 * Append a colored line to a log container element.
 * level: 'ok' | 'warn' | 'error' | 'info'
 */
export function logLine(container, text, level = 'info') {
  if (!container) return;
  const span = document.createElement('span');
  span.className = `log-${level}`;
  span.textContent = text + '\n';
  container.appendChild(span);
  container.scrollTop = container.scrollHeight;
}

/** Format bytes as human-readable string (KB / MB / GB). */
export function formatBytes(n) {
  if (n == null) return '—';
  if (n < 1024) return n + ' B';
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
  if (n < 1024 * 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB';
  return (n / 1024 / 1024 / 1024).toFixed(2) + ' GB';
}

/** Format seconds as human-readable duration (e.g. 2m 34s). */
export function formatDuration(s) {
  if (s == null || isNaN(s)) return '—';
  s = Math.round(s);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  if (m < 60) return rem ? `${m}m ${rem}s` : `${m}m`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  return rm ? `${h}h ${rm}m` : `${h}h`;
}
