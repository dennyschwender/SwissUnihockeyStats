// backend/static/js/admin/system.js
import { fetchJSON, formatBytes, formatDuration } from './utils.js';

let _prevNetIo = null;
let _prevNetTs  = null;

async function loadSystemStats(force = false) {
  if (!force && !document.getElementById('tab-system').classList.contains('active')) return;
  const errEl = document.getElementById('sys-error');
  try {
    const d = await fetchJSON('/admin/api/system');
    const now = Date.now();
    if (!d) {
      errEl.style.display = '';
      errEl.textContent = 'Fetch error — see server logs.';
      document.getElementById('sys-refresh-ts').textContent = 'Error';
      return;
    }
    if (!d.ok) {
      errEl.style.display = '';
      errEl.textContent = 'Error: ' + (d.error || 'unknown');
      return;
    }
    errEl.style.display = 'none';

    // CPU
    const cpuPct = d.cpu.percent ?? 0;
    _sysGauge('sys-cpu-bar', 'sys-cpu-val', cpuPct, cpuPct.toFixed(1) + '%');
    document.getElementById('sys-cpu-sub').textContent =
      d.cpu.count + ' logical core' + (d.cpu.count !== 1 ? 's' : '') +
      (d.cpu.freq_mhz ? ' · ' + Math.round(d.cpu.freq_mhz) + ' MHz' : '');

    // Memory
    const memPct = d.mem.percent ?? 0;
    _sysGauge('sys-mem-bar', 'sys-mem-val', memPct, memPct.toFixed(1) + '%');
    document.getElementById('sys-mem-sub').textContent =
      formatBytes(d.mem.used) + ' / ' + formatBytes(d.mem.total);

    // Disk
    if (d.disk) {
      _sysGauge('sys-disk-bar', 'sys-disk-val', d.disk.percent, d.disk.percent.toFixed(1) + '%');
      document.getElementById('sys-disk-sub').textContent =
        formatBytes(d.disk.used) + ' / ' + formatBytes(d.disk.total) + '  (' + d.disk.path + ')';
    }

    // Network rates (delta between consecutive polls)
    if (_prevNetIo && _prevNetTs) {
      const dt       = Math.max((now - _prevNetTs) / 1000, 0.1);
      const sentRate = Math.max(0, (d.net_io.bytes_sent   - _prevNetIo.bytes_sent)   / dt);
      const recvRate = Math.max(0, (d.net_io.bytes_recv   - _prevNetIo.bytes_recv)   / dt);
      const pSent    = Math.max(0, (d.net_io.packets_sent - _prevNetIo.packets_sent) / dt);
      const pRecv    = Math.max(0, (d.net_io.packets_recv - _prevNetIo.packets_recv) / dt);
      document.getElementById('sys-net-sent').textContent  = formatBytes(sentRate)  + '/s';
      document.getElementById('sys-net-recv').textContent  = formatBytes(recvRate)  + '/s';
      document.getElementById('sys-net-psent').textContent = pSent.toFixed(1) + '/s';
      document.getElementById('sys-net-precv').textContent = pRecv.toFixed(1) + '/s';
    } else {
      document.getElementById('sys-net-sent').textContent  = formatBytes(d.net_io.bytes_sent)  + ' total';
      document.getElementById('sys-net-recv').textContent  = formatBytes(d.net_io.bytes_recv)  + ' total';
      document.getElementById('sys-net-psent').textContent = '—';
      document.getElementById('sys-net-precv').textContent = '—';
    }
    _prevNetIo = { ...d.net_io };
    _prevNetTs = now;

    // Process
    document.getElementById('sys-proc-pid').textContent = d.process.pid;
    document.getElementById('sys-proc-mem').textContent = formatBytes(d.process.rss);
    document.getElementById('sys-proc-cpu').textContent = (d.process.cpu_pct ?? 0).toFixed(1) + '%';
    document.getElementById('sys-proc-thr').textContent = d.process.threads;

    // System / container
    document.getElementById('sys-hostname').textContent = d.hostname;
    document.getElementById('sys-uptime').textContent   = formatDuration(d.uptime_s);
    document.getElementById('sys-cg-limit').textContent = d.cgroup_mem_limit ? formatBytes(d.cgroup_mem_limit) : '—';
    document.getElementById('sys-cg-used').textContent  = d.cgroup_mem_used  ? formatBytes(d.cgroup_mem_used)  : '—';

    document.getElementById('sys-refresh-ts').textContent =
      'Updated ' + new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false});
  } catch(e) {
    document.getElementById('sys-error').style.display = '';
    document.getElementById('sys-error').textContent = 'Fetch error: ' + e.message;
    document.getElementById('sys-refresh-ts').textContent = 'Error';
    console.error('System stats error:', e);
  }
}

function _sysGauge(barId, valId, pct, label) {
  const bar = document.getElementById(barId);
  bar.style.width = Math.min(Math.max(pct, 0), 100) + '%';
  bar.className   = 'sys-gauge-bar' + (pct >= 90 ? ' crit' : pct >= 70 ? ' warn' : '');
  document.getElementById(valId).textContent = label;
}

Object.assign(window, { loadSystemStats });
export { loadSystemStats };
