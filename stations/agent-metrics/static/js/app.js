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

  // LiteLLM 總帳（已用 / 儲值）
  const lEl = document.getElementById("litellm-budget-info");
  if (lEl && budget.litellm) {
    const l = budget.litellm;
    const pct = l.budget_usd > 0 ? Math.round((l.used_usd / l.budget_usd) * 100) : 0;
    lEl.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:baseline">
                       <span style="font-size:1.2rem;font-weight:700;color:var(--peach)">${fmt$(l.used_usd)}<span style="font-size:0.7rem;font-weight:400;color:var(--subtext0)"> 已用</span></span>
                       <span style="font-size:1.2rem;font-weight:700">${fmt$(l.budget_usd)}<span style="font-size:0.7rem;font-weight:400;color:var(--subtext0)"> 儲值</span></span>
                     </div>
                     <div class="progress-track"><div class="progress-fill" style="width:${pct}%;background-color:var(--green)"></div></div>`;
  }

  // Claude 模型（僅顯示 claude-* 開頭）
  const cBody = document.getElementById("claude-model-tbody");
  if (cBody && byModel.claude_models) {
    const claudeOnly = byModel.claude_models.filter(m => m.model.startsWith("claude-"));
    cBody.innerHTML = claudeOnly.length
      ? claudeOnly.map(m => `<tr><td>${m.model}</td><td style="text-align:right">${fmt$(m.cost_usd)}</td></tr>`).join("")
      : `<tr><td colspan="2" class="empty">暫無資料</td></tr>`;
  }

  // LiteLLM 模型 (5 欄: 供應商 | 儲值 | 剩餘 | 已用 | 使用率) + 累計總額
  const lBody = document.getElementById("litellm-model-tbody");
  if (lBody && byModel.litellm_models) {
    if (!byModel.litellm_models.length) {
      lBody.innerHTML = `<tr><td colspan="5" class="empty">暫無資料</td></tr>`;
    } else {
      const rows = byModel.litellm_models.map(m => {
        const name = m.name || m.model;
        const deposit = m.total != null ? fmt$(m.total) : "—";
        const spent = m.spent || m.used_usd || m.cost_usd || 0;
        const remaining = m.remaining != null ? fmt$(m.remaining) : "—";
        const pct = m.pct != null ? m.pct + "%" : "—";
        return `<tr><td>${name}</td><td style="text-align:right">${deposit}</td><td style="text-align:right">${remaining}</td><td style="text-align:right;color:var(--peach)">${fmt$(spent)}</td><td style="text-align:right">${pct}</td></tr>`;
      });
      const totalDeposit = byModel.litellm_models.reduce((s, m) => s + (m.total || 0), 0);
      const totalRemaining = byModel.litellm_models.reduce((s, m) => s + (m.remaining || 0), 0);
      const totalSpent = byModel.litellm_models.reduce((s, m) => s + (m.spent || m.used_usd || m.cost_usd || 0), 0);
      const totalPct = totalDeposit > 0 ? Math.round(totalSpent / totalDeposit * 100 * 10) / 10 + "%" : "—";
      rows.push(`<tr style="border-top:1px solid var(--surface1);font-weight:600"><td>累計</td><td style="text-align:right">${fmt$(totalDeposit)}</td><td style="text-align:right">${fmt$(totalRemaining)}</td><td style="text-align:right;color:var(--peach)">${fmt$(totalSpent)}</td><td style="text-align:right">${totalPct}</td></tr>`);
      lBody.innerHTML = rows.join("");
    }
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
    // 長文字只在環內顯示百分比，完整值放 tooltip
    const ringLabel = val.length > 5 && pctMatch ? pctMatch[0] : val;
    items.push(`<div class="quota-card" title="${val}">
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
          <div class="gauge-value" style="font-size:0.7rem">${ringLabel}</div>
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
    const ringLabel = val.length > 5 && pctMatch ? pctMatch[0] : val;
    items.push(`<div class="quota-card" title="${val}">
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
          <div class="gauge-value" style="font-size:0.7rem">${ringLabel}</div>
        </div>
      </div>
    </div>`);
  }
  grid.innerHTML = items.join("") || '<div class="empty">暫無配額資料</div>';
}

/* ── SSE 連線 ── */
function connectSSE() {
  if (_sse) { _sse.close(); _sse = null; }
  _sse = new EventSource("events/stream");

  _sse.addEventListener("quota", (e) => {
    try { updateQuotaFromSSE(JSON.parse(e.data)); } catch {}
  });

  _sse.addEventListener("usage", (e) => {
    // SSE usage is simplified; do a full refresh for detailed data
    refreshUsage();
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
  updateTimestamp();

  // 啟動 SSE
  connectSSE();

  // 定期全量刷新（作為 SSE 的補充，每 2 分鐘）
  setInterval(() => {
    if (!_autoRefresh) return;
    refreshQuota();
    refreshUsage();
    updateTimestamp();
  }, 120000);
});
