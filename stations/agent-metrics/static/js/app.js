/* app.js — Agent Metrics Dashboard (SSE + 全 Tab 渲染) */
let _sse = null;
let _autoRefresh = true;
const api = async (p) => {
  const r = await fetch(p);
  return r.ok ? r.json() : null;
};
const fmt$ = (v) => "$" + (v || 0).toFixed(2);
const fmtTime = (ts) => {
  if (!ts) return "—";
  const d = new Date(ts);
  if (isNaN(d.getTime())) return ts;
  return d.toLocaleString("zh-TW", { hour12: false, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
};
const fmtBytes = (bps) => {
  if (!bps || bps < 1024) return (bps || 0) + " B/s";
  if (bps < 1048576) return (bps / 1024).toFixed(1) + " KB/s";
  return (bps / 1048576).toFixed(1) + " MB/s";
};

/* ── 用量 Tab ── */
async function refreshUsage() {
  const [budget, byModel] = await Promise.all([api("usage/budget"), api("usage/by-model")]);
  if (!budget || !byModel) return;

  // Claude 總帳
  const cEl = document.getElementById("claude-budget-info");
  if (cEl && budget.claude) {
    cEl.innerHTML = `<div style="font-size:1.5rem;font-weight:700;color:var(--blue)">${fmt$(budget.claude.used_usd)}</div>
                     <div style="font-size:0.7rem;color:var(--subtext0)">Claude (ccusage) 本月花費</div>`;
  }

  // LiteLLM 總帳
  const lEl = document.getElementById("litellm-budget-info");
  if (lEl && budget.litellm) {
    const l = budget.litellm;
    const pct = Math.round((l.used_usd / (l.budget_usd || 1)) * 100);
    lEl.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:baseline">
                       <span style="font-size:1.2rem;font-weight:700">${fmt$(l.remaining_usd)}</span>
                       <span style="font-size:0.7rem;color:var(--subtext0)">共 ${fmt$(l.budget_usd)} 剩餘</span>
                     </div>
                     <div class="progress-track"><div class="progress-fill" style="width:${pct}%;background-color:var(--green)"></div></div>`;
  }

  // Claude 模型
  const cBody = document.getElementById("claude-model-tbody");
  if (cBody && byModel.claude_models) {
    cBody.innerHTML = byModel.claude_models.length
      ? byModel.claude_models.map(m => `<tr><td>${m.model}</td><td style="text-align:right">${fmt$(m.cost_usd)}</td></tr>`).join("")
      : `<tr><td colspan="2" class="empty">暫無資料</td></tr>`;
  }

  // LiteLLM 模型 (4 欄: 供應商 | 剩餘 | 已用 | 使用率)
  const lBody = document.getElementById("litellm-model-tbody");
  if (lBody && byModel.litellm_models) {
    lBody.innerHTML = byModel.litellm_models.length
      ? byModel.litellm_models.map(m => {
          const name = m.name || m.model;
          const spent = m.spent || m.used_usd || m.cost_usd || 0;
          const remaining = m.remaining != null ? fmt$(m.remaining) : "—";
          const pct = m.pct != null ? m.pct + "%" : "—";
          return `<tr><td>${name}</td><td style="text-align:right">${remaining}</td><td style="text-align:right;color:var(--peach)">${fmt$(spent)}</td><td style="text-align:right">${pct}</td></tr>`;
        }).join("")
      : `<tr><td colspan="4" class="empty">暫無資料</td></tr>`;
  }
}

/* ── 配額 Tab ── */
async function refreshQuota() {
  const data = await api("quota/current");
  if (!data) return;
  const grid = document.getElementById("quota-grid");
  if (!grid) return;

  const items = [];
  const f = data.formatted || {};
  const labels = {
    "cc_5h": "Claude 5h", "cc_7d": "Claude 7d", "cc_ex": "Claude Ex",
    "cx_5h": "Codex 5h", "cx_7d": "Codex 7d",
    "gm_pro": "Gemini Pro", "gm_flash": "Gemini Flash"
  };

  for (const [key, label] of Object.entries(labels)) {
    const dashKey = key.replace("_", "-");
    const val = f[dashKey] || f[key] || "?";
    // Parse percentage from display string like "45%" or "45.2%"
    const pctMatch = String(val).match(/([\d.]+)%/);
    const pct = pctMatch ? parseFloat(pctMatch[1]) : null;
    let color = "var(--green)";
    if (pct !== null) {
      if (pct >= 85) color = "var(--red)";
      else if (pct >= 60) color = "var(--yellow)";
    }
    items.push(`<div class="quota-card">
      <div class="quota-label">${label}</div>
      <div class="gauge-container">
        <div class="gauge-ring" style="width:60px;height:60px">
          <svg viewBox="0 0 36 36">
            <circle class="track" cx="18" cy="18" r="15.9"/>
            <circle class="fill" cx="18" cy="18" r="15.9"
              stroke-dasharray="${pct != null ? pct : 0}, 100"
              stroke-dashoffset="0"
              style="stroke:${color}"/>
          </svg>
          <div class="gauge-value" style="font-size:0.7rem">${val}</div>
        </div>
      </div>
    </div>`);
  }
  grid.innerHTML = items.join("") || '<div class="empty">暫無配額資料</div>';
}

function updateQuotaFromSSE(data) {
  const grid = document.getElementById("quota-grid");
  if (!grid || !data) return;

  const labels = {
    "llm_cc_5h": "Claude 5h", "llm_cc_7d": "Claude 7d", "llm_cc_ex": "Claude Ex",
    "llm_cx_5h": "Codex 5h", "llm_cx_7d": "Codex 7d",
    "llm_gm_pro": "Gemini Pro", "llm_gm_flash": "Gemini Flash"
  };

  const items = [];
  for (const [key, label] of Object.entries(labels)) {
    const val = data[key] || "?";
    const pctMatch = String(val).match(/([\d.]+)%/);
    const pct = pctMatch ? parseFloat(pctMatch[1]) : null;
    let color = "var(--green)";
    if (pct !== null) {
      if (pct >= 85) color = "var(--red)";
      else if (pct >= 60) color = "var(--yellow)";
    }
    items.push(`<div class="quota-card">
      <div class="quota-label">${label}</div>
      <div class="gauge-container">
        <div class="gauge-ring" style="width:60px;height:60px">
          <svg viewBox="0 0 36 36">
            <circle class="track" cx="18" cy="18" r="15.9"/>
            <circle class="fill" cx="18" cy="18" r="15.9"
              stroke-dasharray="${pct != null ? pct : 0}, 100"
              stroke-dashoffset="0"
              style="stroke:${color}"/>
          </svg>
          <div class="gauge-value" style="font-size:0.7rem">${val}</div>
        </div>
      </div>
    </div>`);
  }
  grid.innerHTML = items.join("") || '<div class="empty">暫無配額資料</div>';
}

/* ── 工作階段 Tab ── */
async function refreshSessions() {
  const [current, history] = await Promise.all([api("current"), api("history?days=7")]);

  if (current) {
    const el = (id) => document.getElementById(id);
    if (el("stat-today-cost")) el("stat-today-cost").textContent = fmt$(current.total_cost_usd);
    if (el("stat-active")) el("stat-active").textContent = current.active_sessions || current.sessions?.length || 0;
    if (el("stat-sessions")) el("stat-sessions").textContent = current.sessions?.length || 0;
    renderSessionsTable(current.sessions || []);
  }

  if (history) {
    const el = document.getElementById("stat-7d");
    if (el) el.textContent = history.summaries?.length || 0;
  }
}

function renderSessionsTable(sessions) {
  const tbody = document.getElementById("sessions-tbody");
  if (!tbody) return;
  if (!sessions.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty">目前無活躍工作階段</td></tr>';
    return;
  }
  tbody.innerHTML = sessions.map(s => `<tr>
    <td><span class="badge badge-blue">${s.cli || "claude"}</span></td>
    <td>${s.model || "—"}</td>
    <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${s.cwd || ""}">${s.cwd || "—"}</td>
    <td style="color:var(--peach);font-weight:600">${fmt$(s.cost_usd)}</td>
    <td style="font-size:0.7rem;color:var(--subtext0)">${fmtTime(s.last_seen)}</td>
  </tr>`).join("");
}

/* ── 系統 Tab ── */
async function refreshSystem() {
  const data = await api("sysmon/current");
  if (!data || data.error) return;
  updateSystemFromData(data);
}

function updateSystemFromData(data) {
  // CPU
  if (typeof setGauge === "function") {
    setGauge("cpu-gauge", data.cpu_pct || 0, "cpu-pct", "cpu-details", data.cpu_display || "");
    setGauge("mem-gauge", data.mem_pct || 0, "mem-pct", "mem-details", data.mem_display || "");
    setGauge("disk-gauge", data.disk_pct || 0, "disk-pct", "disk-details", data.disk_display || "");
  }

  // 網路
  const netEl = document.getElementById("net-info");
  if (netEl) {
    netEl.innerHTML = `
      <div class="net-row"><span class="net-label">下載</span><span class="net-value" style="color:var(--green)">${fmtBytes(data.net_rx_bps)}</span></div>
      <div class="net-row"><span class="net-label">上傳</span><span class="net-value" style="color:var(--blue)">${fmtBytes(data.net_tx_bps)}</span></div>`;
  }

  // Claude 程序
  const procsEl = document.getElementById("claude-procs");
  if (procsEl) {
    const active = data.cc_active || 0;
    const idle = data.cc_idle || 0;
    const mem = (data.cc_mem_mb || 0).toFixed(0);
    procsEl.innerHTML = active + idle > 0
      ? `<div style="display:flex;gap:1rem;align-items:center;padding:0.5rem 0">
           <span><span class="badge badge-green">${active} 活躍</span></span>
           <span><span class="badge badge-yellow">${idle} 閒置</span></span>
           <span style="font-size:0.7rem;color:var(--subtext0)">記憶體: ${mem} MB</span>
         </div>`
      : '<div class="empty">無 Claude 程序</div>';
  }
}

/* ── 運維 Tab ── */
async function refreshOps() {
  const [guardian, sweep, maestro] = await Promise.all([
    api("guardian/log?hours=48"),
    api("sweep/log?hours=48"),
    api("maestro/runs?limit=20")
  ]);

  renderLogList("guardian-list", guardian?.actions, "守衛");
  renderLogList("sweep-list", sweep?.actions, "清掃");
  renderMaestroList("maestro-list", Array.isArray(maestro) ? maestro : maestro?.runs);
}

function renderLogList(elId, actions, emptyLabel) {
  const el = document.getElementById(elId);
  if (!el) return;
  if (!actions || !actions.length) {
    el.innerHTML = `<div class="empty">近 48 小時無${emptyLabel}動作</div>`;
    return;
  }
  el.innerHTML = actions.slice(0, 50).map(a => {
    const levelBadge = a.level === "WARN" ? "badge-yellow" : a.level === "CRIT" ? "badge-red" : "badge-green";
    return `<div class="log-item">
      <span class="log-time">${fmtTime(a.ts)}</span>
      <span class="badge ${levelBadge}">${a.level || "INFO"}</span>
      <span class="log-detail">${a.process_name || ""} — ${a.action || ""} ${a.result || ""}</span>
    </div>`;
  }).join("");
}

function renderMaestroList(elId, runs) {
  const el = document.getElementById(elId);
  if (!el) return;
  if (!runs || !runs.length) {
    el.innerHTML = '<div class="empty">暫無排程記錄</div>';
    return;
  }
  el.innerHTML = runs.slice(0, 20).map(r => {
    const statusBadge = r.status === "completed" ? "badge-green" : r.status === "failed" ? "badge-red" : "badge-yellow";
    return `<div class="log-item">
      <span class="log-time">${fmtTime(r.started_at)}</span>
      <span class="badge ${statusBadge}">${r.status || "—"}</span>
      <span class="log-detail">${r.name || ""} [${r.pattern || "solo"}] ${r.duration_s ? r.duration_s + "s" : ""}</span>
    </div>`;
  }).join("");
}

/* ── SSE 連線 ── */
function connectSSE() {
  if (_sse) { _sse.close(); _sse = null; }
  _sse = new EventSource("events/stream");

  _sse.addEventListener("system", (e) => {
    try { updateSystemFromData(JSON.parse(e.data)); } catch {}
  });

  _sse.addEventListener("sessions", (e) => {
    try {
      const d = JSON.parse(e.data);
      const el = (id) => document.getElementById(id);
      if (el("stat-today-cost")) el("stat-today-cost").textContent = fmt$(d.total_cost_usd);
      if (el("stat-active")) el("stat-active").textContent = d.active_sessions || d.sessions?.length || 0;
      if (el("stat-sessions")) el("stat-sessions").textContent = d.sessions?.length || 0;
      renderSessionsTable(d.sessions || []);
    } catch {}
  });

  _sse.addEventListener("quota", (e) => {
    try { updateQuotaFromSSE(JSON.parse(e.data)); } catch {}
  });

  _sse.addEventListener("usage", (e) => {
    // SSE usage is simplified; do a full refresh for detailed data
    refreshUsage();
  });

  _sse.addEventListener("operations", (e) => {
    try {
      const d = JSON.parse(e.data);
      renderMaestroList("maestro-list", d.runs);
    } catch {}
  });

  _sse.onerror = () => {
    _sse.close();
    _sse = null;
    // 重連延遲 5 秒
    setTimeout(() => { if (_autoRefresh) connectSSE(); }, 5000);
  };
}

/* ── 更新時間戳 ── */
function updateTimestamp() {
  const el = document.getElementById("last-updated");
  if (el) el.textContent = "更新: " + new Date().toLocaleTimeString("zh-TW", { hour12: false });
}

/* ── 初始化 ── */
document.addEventListener("DOMContentLoaded", () => {
  // Tab 切換
  document.querySelectorAll(".tab-btn").forEach(b => b.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn, .tab-panel").forEach(x => x.classList.remove("active"));
    b.classList.add("active");
    document.getElementById("panel-" + b.dataset.tab).classList.add("active");
  }));

  // 自動更新開關
  const toggle = document.getElementById("auto-refresh-toggle");
  if (toggle) {
    toggle.addEventListener("click", () => {
      _autoRefresh = !_autoRefresh;
      document.getElementById("toggle-track").classList.toggle("active", _autoRefresh);
      if (_autoRefresh) {
        connectSSE();
      } else if (_sse) {
        _sse.close();
        _sse = null;
      }
    });
  }

  // 初次載入所有 Tab 資料
  refreshQuota();
  refreshUsage();
  refreshSessions();
  refreshSystem();
  refreshOps();
  updateTimestamp();

  // 啟動 SSE
  connectSSE();

  // 定期全量刷新（作為 SSE 的補充，每 2 分鐘）
  setInterval(() => {
    if (!_autoRefresh) return;
    refreshQuota();
    refreshUsage();
    refreshSessions();
    refreshOps();
    updateTimestamp();
  }, 120000);
});
