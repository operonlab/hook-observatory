/* app.js — Agent Metrics Dashboard fetch + render logic */

// --- State ---
let autoRefresh = true;
const timers = {};

// --- Tab Switching ---
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('panel-' + btn.dataset.tab).classList.add('active');
  });
});

// --- Auto Refresh Toggle ---
const toggleEl = document.getElementById('auto-refresh-toggle');
if (toggleEl) {
  toggleEl.addEventListener('click', () => {
    autoRefresh = !autoRefresh;
    const track = document.getElementById('toggle-track');
    track.classList.toggle('active', autoRefresh);
    if (autoRefresh) startTimers();
    else stopTimers();
  });
}

// --- API Helpers ---
async function api(path) {
  try {
    const res = await fetch(path);
    if (!res.ok) throw new Error(res.statusText);
    return await res.json();
  } catch (e) {
    console.warn(`[API] ${path} failed:`, e);
    return null;
  }
}

function relTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return Math.round(diff) + 's ago';
  if (diff < 3600) return Math.round(diff / 60) + 'm ago';
  if (diff < 86400) return Math.round(diff / 3600) + 'h ago';
  return d.toLocaleDateString();
}

function fmt$(v) {
  if (v == null) return '$0.00';
  return '$' + Number(v).toFixed(2);
}

function fmtBytes(bps) {
  if (bps == null || bps === 0) return '0 B/s';
  if (bps < 1024) return bps + ' B/s';
  if (bps < 1048576) return (bps / 1024).toFixed(1) + ' KB/s';
  return (bps / 1048576).toFixed(1) + ' MB/s';
}

function updateTimestamp() {
  const el = document.getElementById('last-updated');
  if (el) el.textContent = new Date().toLocaleTimeString();
}

// ========================================================================
// TAB: Quotas
// ========================================================================

async function refreshQuotas() {
  const data = await api('/quota/current');
  if (!data) return;

  const quotaGrid = document.getElementById('quota-grid');
  if (!quotaGrid) return;

  const items = [
    { label: 'CC 5h', key: 'cc_5h', parsed: data.parsed?.cc?.['5h'] },
    { label: 'CC 7d', key: 'cc_7d', parsed: data.parsed?.cc?.['7d'] },
    { label: 'CC Extra', key: 'cc_ex', parsed: data.parsed?.cc?.ex },
    { label: 'CX 5h', key: 'cx_5h', parsed: data.parsed?.cx?.['5h'] },
    { label: 'CX 7d', key: 'cx_7d', parsed: data.parsed?.cx?.['7d'] },
    { label: 'GM Pro', key: 'gm_pro', parsed: data.parsed?.gm?.pro },
    { label: 'GM Flash', key: 'gm_flash', parsed: data.parsed?.gm?.flash },
  ];

  quotaGrid.innerHTML = items.map(it => {
    const formatted = data.formatted?.[it.key] || '?';
    const pctMatch = (it.parsed || formatted).toString().match(/(\d+)%/);
    const pct = pctMatch ? parseInt(pctMatch[1]) : 0;
    const gaugeId = 'qg-' + it.key;
    const valId = 'qv-' + it.key;

    return `
      <div class="quota-card">
        <div class="quota-label">${it.label}</div>
        <div class="gauge-ring" style="width:60px;height:60px">
          <svg viewBox="0 0 36 36">
            <circle class="track" cx="18" cy="18" r="15.9"/>
            <circle class="fill" id="${gaugeId}" cx="18" cy="18" r="15.9"
              stroke-dasharray="100, 100" stroke-dashoffset="100"/>
          </svg>
          <div class="gauge-value" id="${valId}" style="font-size:0.8rem">—</div>
        </div>
        <div class="quota-value">${formatted}</div>
      </div>
    `;
  }).join('');

  // Set gauge values after DOM update
  requestAnimationFrame(() => {
    items.forEach(it => {
      const formatted = data.formatted?.[it.key] || '?';
      const pctMatch = (it.parsed || formatted).toString().match(/(\d+)%/);
      const pct = pctMatch ? parseInt(pctMatch[1]) : 0;
      setGauge('qg-' + it.key, pct, 'qv-' + it.key);
    });
  });

  updateTimestamp();
}

// ========================================================================
// TAB: Sessions
// ========================================================================

async function refreshSessions() {
  const [current, history] = await Promise.all([
    api('/current'),
    api('/history?days=7'),
  ]);

  // Stat cards
  const statsEl = document.getElementById('session-stats');
  if (statsEl && current) {
    const totalCost = current.total_cost_usd || 0;
    const activeSessions = current.active_sessions || 0;
    const sessionCount = current.sessions?.length || 0;

    statsEl.innerHTML = `
      <div class="stat-card">
        <div class="stat-label">Today Cost</div>
        <div class="stat-value">${fmt$(totalCost)}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Active</div>
        <div class="stat-value">${activeSessions}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Sessions</div>
        <div class="stat-value">${sessionCount}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">7d Summaries</div>
        <div class="stat-value">${history?.count || 0}</div>
      </div>
    `;
  }

  // Session table
  const tbody = document.getElementById('sessions-tbody');
  if (tbody && current?.sessions) {
    const sessions = current.sessions;
    if (!sessions.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty">No sessions today</td></tr>';
      return;
    }
    tbody.innerHTML = sessions.map(s => {
      const cli = (s.cli || 'claude').toUpperCase();
      const cliBadge = cli === 'CLAUDE' ? 'badge-blue' :
                       cli === 'CODEX' ? 'badge-green' :
                       cli === 'GEMINI' ? 'badge-mauve' : 'badge-teal';
      const model = s.model || '—';
      const cost = fmt$(s.cost_usd || s.total_cost);
      const lastSeen = relTime(s.last_seen);
      const cwd = s.cwd || '—';

      return `
        <tr>
          <td><span class="badge ${cliBadge}">${cli}</span></td>
          <td>${model}</td>
          <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${cwd}">${cwd}</td>
          <td style="color:var(--peach);font-weight:600">${cost}</td>
          <td>${lastSeen}</td>
        </tr>
      `;
    }).join('');
  }

  updateTimestamp();
}

// ========================================================================
// TAB: System
// ========================================================================

async function refreshSystem() {
  const data = await api('/sysmon/current');
  if (!data || data.error) return;

  // CPU
  setGauge('cpu-gauge', data.cpu_pct || 0, 'cpu-pct', 'cpu-details', data.cpu_display || '');

  // Memory
  setGauge('mem-gauge', data.mem_pct || 0, 'mem-pct', 'mem-details',
    `${data.mem_used_gb || 0}/${data.mem_total_gb || 0} GB | P:${data.mem_pressure ?? '?'}`);

  // Disk
  setGauge('disk-gauge', data.disk_pct || 0, 'disk-pct', 'disk-details',
    `${data.disk_used_gb || 0}/${data.disk_total_gb || 0} GB`);

  // Network
  const netEl = document.getElementById('net-info');
  if (netEl) {
    netEl.innerHTML = `
      <div class="net-row">
        <span class="net-label">RX</span>
        <span class="net-value" style="color:var(--green)">${fmtBytes(data.net_rx_bps)}</span>
      </div>
      <div class="net-row">
        <span class="net-label">TX</span>
        <span class="net-value" style="color:var(--blue)">${fmtBytes(data.net_tx_bps)}</span>
      </div>
    `;
  }

  // Claude processes
  const claudeEl = document.getElementById('claude-procs');
  if (claudeEl) {
    const cc = data.cc_active || 0;
    const ci = data.cc_idle || 0;
    const cm = data.cc_mem_mb || 0;
    claudeEl.innerHTML = `
      <div style="font-size:0.75rem">
        Active: <strong>${cc}</strong> &nbsp; Idle: <strong>${ci}</strong>
        &nbsp; MEM: <strong>${Math.round(cm)} MB</strong>
      </div>
    `;
  }

  updateTimestamp();
}

// ========================================================================
// TAB: Usage
// ========================================================================

async function refreshUsage() {
  const [budget, trends, byModel] = await Promise.all([
    api('/usage/budget'),
    api('/usage/trends?days=30'),
    api('/usage/by-model?days=30'),
  ]);

  // Budget progress
  const budgetEl = document.getElementById('budget-info');
  if (budgetEl && budget) {
    const pct = budget.used_pct || 0;
    budgetEl.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:0.5rem">
        <span style="font-size:1.2rem;font-weight:700">${fmt$(budget.used_usd)}</span>
        <span style="font-size:0.7rem;color:var(--subtext0)">of ${fmt$(budget.budget_usd)}</span>
      </div>
      ${progressBar(pct, `${pct}% used`, `${budget.days_elapsed || 0}d elapsed`)}
      <div style="font-size:0.7rem;color:var(--subtext0);margin-top:0.25rem">
        Remaining: ${fmt$(budget.remaining_usd)}
      </div>
    `;
  }

  // Trends sparkline
  const trendsEl = document.getElementById('trends-chart');
  if (trendsEl && trends?.daily) {
    const costs = trends.daily.map(d => d.cost || 0);
    renderSparkline(trendsEl, costs, { color: '#89b4fa', fill: true, height: 60 });

    const projEl = document.getElementById('trends-projection');
    if (projEl && trends.projection) {
      projEl.textContent = `Projected: ${fmt$(trends.projection.monthly_estimate)}`;
    }
  }

  // By model table
  const modelTbody = document.getElementById('model-tbody');
  if (modelTbody && byModel?.models) {
    const models = byModel.models;
    if (!models.length) {
      modelTbody.innerHTML = '<tr><td colspan="4" class="empty">No model data</td></tr>';
    } else {
      modelTbody.innerHTML = models.map(m => `
        <tr>
          <td>${m.model || '—'}</td>
          <td style="text-align:right">${(m.total_tokens || 0).toLocaleString()}</td>
          <td style="text-align:right;color:var(--peach);font-weight:600">${fmt$(m.cost)}</td>
          <td style="text-align:right">${m.pct ? m.pct + '%' : '—'}</td>
        </tr>
      `).join('');
    }
  }

  updateTimestamp();
}

// ========================================================================
// TAB: Operations
// ========================================================================

async function refreshOps() {
  const [guardian, sweep, runs] = await Promise.all([
    api('/guardian/log?hours=48'),
    api('/sweep/log?hours=48'),
    api('/maestro/runs?limit=20'),
  ]);

  // Guardian log
  const guardianEl = document.getElementById('guardian-list');
  if (guardianEl) {
    const actions = guardian?.actions || [];
    if (!actions.length) {
      guardianEl.innerHTML = '<div class="empty">No guardian actions (48h)</div>';
    } else {
      guardianEl.innerHTML = actions.map(a => {
        const lvlClass = a.level === 'CRIT' ? 'badge-red' : 'badge-yellow';
        const resClass = a.result === 'success' ? 'badge-green' :
                        a.result === 'skipped' ? 'badge-blue' : 'badge-peach';
        return `
          <div class="log-item">
            <span class="log-time">${relTime(a.ts)}</span>
            <span class="badge ${lvlClass}">${a.level}</span>
            <span class="badge ${resClass}">${a.result}</span>
            <span class="log-detail">${a.process_name || ''} (PID ${a.pid || '?'}) ${a.action} ${a.detail || ''}</span>
          </div>
        `;
      }).join('');
    }
  }

  // Sweep log
  const sweepEl = document.getElementById('sweep-list');
  if (sweepEl) {
    const actions = sweep?.actions || [];
    if (!actions.length) {
      sweepEl.innerHTML = '<div class="empty">No sweep actions (48h)</div>';
    } else {
      sweepEl.innerHTML = actions.map(a => {
        const resClass = a.result === 'success' ? 'badge-green' :
                        a.result === 'already_dead' ? 'badge-blue' :
                        a.result === 'warn' ? 'badge-yellow' : 'badge-peach';
        return `
          <div class="log-item">
            <span class="log-time">${relTime(a.ts)}</span>
            <span class="badge badge-mauve">${a.priority}</span>
            <span class="badge ${resClass}">${a.result}</span>
            <span class="log-detail">${a.process_name || ''} (PID ${a.pid || '?'}) ${a.detail || ''}</span>
          </div>
        `;
      }).join('');
    }
  }

  // Maestro runs
  const runsEl = document.getElementById('maestro-list');
  if (runsEl) {
    const runsList = Array.isArray(runs) ? runs : [];
    if (!runsList.length) {
      runsEl.innerHTML = '<div class="empty">No dispatch history</div>';
    } else {
      runsEl.innerHTML = runsList.map(r => {
        const statusClass = r.status === 'completed' ? 'badge-green' :
                           r.status === 'running' ? 'badge-blue' : 'badge-red';
        return `
          <div class="log-item">
            <span class="log-time">${relTime(r.started_at || r.created_at)}</span>
            <span class="badge ${statusClass}">${r.status || '?'}</span>
            <span class="badge badge-teal">${r.pattern || '?'}</span>
            <span class="log-detail">${r.name || r.id || '—'} (${r.duration_s || '?'}s)</span>
          </div>
        `;
      }).join('');
    }
  }

  updateTimestamp();
}

// ========================================================================
// Timer Management
// ========================================================================

function startTimers() {
  stopTimers();
  // Initial load
  refreshQuotas();
  refreshSessions();
  refreshSystem();
  refreshUsage();
  refreshOps();

  // Intervals: System 5s, Sessions 10s, Quotas 60s, Usage 60s, Ops 30s
  timers.system = setInterval(refreshSystem, 5000);
  timers.sessions = setInterval(refreshSessions, 10000);
  timers.quotas = setInterval(refreshQuotas, 60000);
  timers.usage = setInterval(refreshUsage, 60000);
  timers.ops = setInterval(refreshOps, 30000);
}

function stopTimers() {
  Object.values(timers).forEach(t => clearInterval(t));
  Object.keys(timers).forEach(k => delete timers[k]);
}

// --- Boot ---
document.addEventListener('DOMContentLoaded', startTimers);
