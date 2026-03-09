// backend/static/js/admin/trends.js
import { fetchJSON } from './utils.js';

let _trendsRange = 30;
const _charts = {};

async function loadTrends() {
  const data = await fetchJSON(`/admin/api/stats/history?days=${_trendsRange}`);
  if (!data || data.length === 0) return;

  // Reverse so oldest→newest on x-axis
  const rows = [...data].reverse();
  const labels = rows.map(r => (r.ts || '').slice(0, 16).replace('T', ' '));

  _renderLine('chart-db-size', labels, [
    {
      label: 'DB Size (MB)',
      data: rows.map(r => ((r.db_size_bytes || 0) / 1024 / 1024).toFixed(2)),
      borderColor: 'var(--swiss-red)',
      backgroundColor: 'rgba(255,0,0,0.08)',
      tension: 0.3,
      fill: true,
    },
  ]);

  _renderLine('chart-records', labels, [
    { label: 'Games',   data: rows.map(r => r.games   || 0), borderColor: '#58a6ff', tension: 0.3 },
    { label: 'Players', data: rows.map(r => r.players || 0), borderColor: '#3fb950', tension: 0.3 },
    { label: 'Events',  data: rows.map(r => r.events  || 0), borderColor: '#d29922', tension: 0.3 },
  ]);

  _renderBar('chart-jobs', labels, [
    { label: 'Jobs Run', data: rows.map(r => r.jobs_run    || 0), backgroundColor: 'rgba(31,111,235,0.6)' },
    { label: 'Errors',   data: rows.map(r => r.jobs_errors || 0), backgroundColor: 'rgba(255,0,0,0.7)' },
  ]);

  _renderLine('chart-duration', labels, [
    {
      label: 'Avg Duration (s)',
      data: rows.map(r => r.avg_job_duration_s != null ? Number(r.avg_job_duration_s).toFixed(1) : 0),
      borderColor: '#3fb950',
      tension: 0.3,
    },
  ]);
}

function _chartDefaults() {
  return {
    responsive: true,
    animation: false,
    plugins: { legend: { labels: { color: '#c9d1d9', font: { size: 11 } } } },
    scales: {
      x: { ticks: { color: '#8b949e', maxTicksLimit: 8 }, grid: { color: '#21262d' } },
      y: { ticks: { color: '#8b949e' }, grid: { color: '#21262d' }, beginAtZero: true },
    },
  };
}

function _renderLine(canvasId, labels, datasets) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;
  if (_charts[canvasId]) _charts[canvasId].destroy();
  _charts[canvasId] = new Chart(ctx, { type: 'line', data: { labels, datasets }, options: _chartDefaults() });
}

function _renderBar(canvasId, labels, datasets) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;
  if (_charts[canvasId]) _charts[canvasId].destroy();
  _charts[canvasId] = new Chart(ctx, { type: 'bar', data: { labels, datasets }, options: _chartDefaults() });
}

function setTrendsRange(days) {
  _trendsRange = days;
  document.querySelectorAll('.trends-range-btns .btn').forEach(b => b.classList.remove('btn-active'));
  const btn = document.getElementById(`tr-${days}d`);
  if (btn) btn.classList.add('btn-active');
  loadTrends();
}

Object.assign(window, { setTrendsRange, loadTrends });
