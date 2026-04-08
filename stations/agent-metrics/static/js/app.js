/* app.js — Agent Metrics Dashboard (Mission Control Edition) */
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

/* ── Lucide-style inline SVG icons ── */
const ICONS = {
  externalLink: `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg>`,
  trophy:       `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"/><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/><path d="M4 22h16"/><path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20 7 22"/><path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20 17 22"/><path d="M18 2H6v7a6 6 0 0 0 12 0V2Z"/></svg>`,
  code:         `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>`,
  calculator:   `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="16" height="20" x="4" y="2" rx="2"/><line x1="8" x2="16" y1="6" y2="6"/><line x1="16" x2="16" y1="14" y2="18"/><path d="M16 10h.01"/><path d="M12 10h.01"/><path d="M8 10h.01"/><path d="M12 14h.01"/><path d="M8 14h.01"/><path d="M12 18h.01"/><path d="M8 18h.01"/></svg>`,
  globe:        `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/></svg>`,
  zap:          `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/></svg>`,
  coins:        `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="6"/><path d="M18.09 10.37A6 6 0 1 1 10.34 18"/><path d="M7 6h1v4"/><path d="m16.71 13.88.7.71-2.82 2.82"/></svg>`,
  gift:         `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="8" width="18" height="4" rx="1"/><path d="M12 8v13"/><path d="M19 12v7a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2v-7"/><path d="M7.5 8a2.5 2.5 0 0 1 0-5A4.8 8 0 0 1 12 8a4.8 8 0 0 1 4.5-5 2.5 2.5 0 0 1 0 5"/></svg>`,
  brain:        `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z"/><path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z"/></svg>`,
  target:       `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>`,
  lightbulb:    `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5"/><path d="M9 18h6"/><path d="M10 22h4"/></svg>`,
};

/* Provider dashboard URLs */
const PROVIDER_DASHBOARDS = {
  minimax:   "https://platform.minimax.io/user-center/payment/balance",
  moonshot:  "https://platform.moonshot.ai/console/account",
  zhipu:     "https://z.ai/manage-apikey/billing",
  deepseek:  "https://platform.deepseek.com/usage",
  dashscope: "https://modelstudio.console.alibabacloud.com/ap-southeast-1/?tab=dashboard#/model-usage/free-quota",
  xai:       "https://console.x.ai/team/f0ca6117-e73f-4fec-b5ab-4391eb612200/billing",
  google:    "https://console.cloud.google.com/billing/credits?hl=zh-tw",
};

/* ═══════════════════════════════════════════
   用量 Tab
   ═══════════════════════════════════════════ */
async function refreshUsage() {
  const [budget, byModel] = await Promise.all([api("usage/budget"), api("usage/by-model")]);
  if (!budget || !byModel) return;

  // ── Summary row ──
  const sTotal = document.getElementById("summary-total-spend");
  const sRemaining = document.getElementById("summary-litellm-remaining");
  const sPct = document.getElementById("summary-litellm-pct");

  if (budget.claude && sTotal) {
    sTotal.querySelector(".summary-stat-value").textContent = fmt$(budget.claude.used_usd);
  }
  if (budget.litellm && sRemaining) {
    sRemaining.querySelector(".summary-stat-value").textContent = fmt$(budget.litellm.remaining ?? (budget.litellm.budget_usd - budget.litellm.used_usd));
  }
  if (budget.litellm && sPct) {
    const l = budget.litellm;
    const pct = l.budget_usd > 0 ? Math.round((l.used_usd / l.budget_usd) * 100) : 0;
    sPct.querySelector(".summary-stat-value").textContent = pct + "%";
  }

  // ── Claude 總帳 ──
  const cEl = document.getElementById("claude-budget-info");
  if (cEl && budget.claude) {
    cEl.innerHTML = `
      <div style="font-family:var(--font-mono);font-size:1.6rem;font-weight:700;color:var(--blue);line-height:1">${fmt$(budget.claude.used_usd)}</div>
      <div style="font-size:0.65rem;color:var(--subtext0);margin-top:0.35rem;text-transform:uppercase;letter-spacing:0.05em">Claude (ccusage) 本月花費</div>`;
  }

  // ── LiteLLM 總帳 ──
  const lEl = document.getElementById("litellm-budget-info");
  if (lEl && budget.litellm) {
    const l = budget.litellm;
    const pct = l.budget_usd > 0 ? Math.round((l.used_usd / l.budget_usd) * 100) : 0;
    let barCls = '';
    if (pct >= 90) barCls = 'crit';
    else if (pct >= 70) barCls = 'warn';
    lEl.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:baseline;gap:1rem">
        <span style="font-family:var(--font-mono);font-size:1.3rem;font-weight:700;color:var(--peach)">${fmt$(l.used_usd)}<span style="font-size:0.65rem;font-weight:400;color:var(--subtext0);margin-left:0.3rem">已用</span></span>
        <span style="font-family:var(--font-mono);font-size:1.3rem;font-weight:700">${fmt$(l.budget_usd)}<span style="font-size:0.65rem;font-weight:400;color:var(--subtext0);margin-left:0.3rem">儲值</span></span>
      </div>
      <div class="progress-track" style="margin-top:0.6rem">
        <div class="progress-fill ${barCls}" style="width:${pct}%"></div>
      </div>
      <div style="font-family:var(--font-mono);font-size:0.62rem;color:var(--subtext0);text-align:right;margin-top:0.2rem">${pct}%</div>`;
  }

  // ── Claude 模型表 ──
  const cBody = document.getElementById("claude-model-tbody");
  if (cBody && byModel.claude_models) {
    const claudeOnly = byModel.claude_models.filter(m => m.model.startsWith("claude-"));
    cBody.innerHTML = claudeOnly.length
      ? claudeOnly.map((m, i) => `<tr><td>${m.model}</td><td style="text-align:right;color:var(--blue)">${fmt$(m.cost_usd)}</td></tr>`).join("")
      : `<tr><td colspan="2" class="empty">暫無資料</td></tr>`;
  }

  // ── LiteLLM 模型表 ──
  const lBody = document.getElementById("litellm-model-tbody");
  if (lBody && byModel.litellm_models) {
    if (!byModel.litellm_models.length) {
      lBody.innerHTML = `<tr><td colspan="5" class="empty">暫無資料</td></tr>`;
    } else {
      const rows = byModel.litellm_models.map((m, idx) => {
        const name = m.name || m.model;
        const dashUrl = PROVIDER_DASHBOARDS[name];
        const linkBtn = dashUrl
          ? `<a class="provider-link" href="${dashUrl}" target="_blank" rel="noopener" title="開啟儀表板" aria-label="${name} 儀表板">${ICONS.externalLink}</a>`
          : "";
        const deposit   = m.total != null ? fmt$(m.total) : "—";
        const spent     = m.spent || m.used_usd || m.cost_usd || 0;
        const remaining = m.remaining != null ? fmt$(m.remaining) : "—";
        const pct       = m.pct != null ? m.pct : null;
        const pctStr    = pct != null ? pct + "%" : "—";
        const note      = m.note ? `<span style="font-size:0.62rem;color:var(--subtext0);display:block;font-family:var(--font-ui)">${m.note}</span>` : "";

        // Usage rate cell with mini progress bar
        let pctCell;
        if (pct != null) {
          let pctColor = 'var(--green)';
          if (pct >= 90) pctColor = 'var(--red)';
          else if (pct >= 70) pctColor = 'var(--yellow)';
          pctCell = `<td style="text-align:right">
            <span style="font-weight:600;color:${pctColor}">${pctStr}</span>
          </td>`;
        } else {
          pctCell = `<td style="text-align:right;color:var(--overlay0)">—</td>`;
        }

        return `<tr>
          <td><span style="font-family:var(--font-ui);font-weight:600">${name}</span>${linkBtn}${note}</td>
          <td style="text-align:right">${deposit}</td>
          <td style="text-align:right;color:var(--teal)">${remaining}</td>
          <td style="text-align:right;color:var(--peach)">${fmt$(spent)}</td>
          ${pctCell}
        </tr>`;
      });

      const totalDeposit   = byModel.litellm_models.reduce((s, m) => s + (m.total || 0), 0);
      const totalRemaining = byModel.litellm_models.reduce((s, m) => s + (m.remaining || 0), 0);
      const totalSpent     = byModel.litellm_models.reduce((s, m) => s + (m.spent || m.used_usd || m.cost_usd || 0), 0);
      const totalPct       = totalDeposit > 0 ? Math.round(totalSpent / totalDeposit * 100 * 10) / 10 + "%" : "—";

      rows.push(`<tr style="border-top:1px solid var(--surface1)">
        <td style="font-weight:700;font-family:var(--font-ui)">累計</td>
        <td style="text-align:right;font-weight:700">${fmt$(totalDeposit)}</td>
        <td style="text-align:right;font-weight:700;color:var(--teal)">${fmt$(totalRemaining)}</td>
        <td style="text-align:right;font-weight:700;color:var(--peach)">${fmt$(totalSpent)}</td>
        <td style="text-align:right;font-weight:700">${totalPct}</td>
      </tr>`);

      lBody.innerHTML = rows.join("");
    }
  }
}

/* ═══════════════════════════════════════════
   配額 Tab — internal render helper
   ═══════════════════════════════════════════ */
function _buildQuotaItems(keyMap, sourceObj) {
  const items = [];
  for (const [key, label] of Object.entries(keyMap)) {
    const val = sourceObj[key] || "?";
    const pctMatch = String(val).match(/([\d.]+)%/);
    const pct = pctMatch ? parseFloat(pctMatch[1]) : null;
    const ringLabel = val.length > 5 && pctMatch ? pctMatch[0] : val;
    items.push(buildGaugeCard(label, pct, ringLabel, String(val)));
  }
  return items;
}

async function refreshQuota() {
  const data = await api("quota/current");
  if (!data) return;

  const f = data.formatted || {};

  // Remap keys: API uses dash or underscore variants
  const normalize = (obj) => {
    const out = {};
    for (const [k, v] of Object.entries(obj)) {
      out[k.replace(/-/g, "_")] = v;
    }
    return out;
  };
  const norm = normalize(f);

  const claudeKeys = {
    "cc_5h": "Claude 5h", "cc_7d": "Claude 7d", "cc_ex": "Claude Ex"
  };
  const otherKeys = {
    "cx_5h": "Codex 5h", "cx_7d": "Codex 7d",
    "gm_pro": "Gemini Pro", "gm_flash": "Gemini Flash"
  };

  const gridClaude = document.getElementById("quota-grid-claude");
  const gridOther  = document.getElementById("quota-grid-other");

  // Check if sectioned grids exist
  if (gridClaude && gridOther) {
    const claudeItems = _buildQuotaItems(claudeKeys, norm);
    const otherItems  = _buildQuotaItems(otherKeys, norm);

    gridClaude.innerHTML = claudeItems.join("") || '<div class="empty">暫無配額資料</div>';
    gridOther.innerHTML  = otherItems.join("") || '<div class="empty">暫無配額資料</div>';
  } else {
    // Fallback: unified grid
    const grid = document.getElementById("quota-grid");
    if (!grid) return;
    const allKeys = { ...claudeKeys, ...otherKeys };
    const allItems = _buildQuotaItems(allKeys, norm);
    grid.style.display = "";
    grid.innerHTML = allItems.join("") || '<div class="empty">暫無配額資料</div>';
  }
}

function updateQuotaFromSSE(data) {
  const labels = {
    "llm_cc_5h": "Claude 5h", "llm_cc_7d": "Claude 7d", "llm_cc_ex": "Claude Ex",
    "llm_cx_5h": "Codex 5h", "llm_cx_7d": "Codex 7d",
    "llm_gm_pro": "Gemini Pro", "llm_gm_flash": "Gemini Flash"
  };

  const claudeKeys = { "llm_cc_5h": "Claude 5h", "llm_cc_7d": "Claude 7d", "llm_cc_ex": "Claude Ex" };
  const otherKeys  = { "llm_cx_5h": "Codex 5h", "llm_cx_7d": "Codex 7d", "llm_gm_pro": "Gemini Pro", "llm_gm_flash": "Gemini Flash" };

  const gridClaude = document.getElementById("quota-grid-claude");
  const gridOther  = document.getElementById("quota-grid-other");

  if (gridClaude && gridOther) {
    const claudeItems = _buildQuotaItems(claudeKeys, data);
    const otherItems  = _buildQuotaItems(otherKeys, data);
    gridClaude.innerHTML = claudeItems.join("") || '<div class="empty">暫無配額資料</div>';
    gridOther.innerHTML  = otherItems.join("") || '<div class="empty">暫無配額資料</div>';
  } else {
    const grid = document.getElementById("quota-grid");
    if (!grid) return;
    const allItems = _buildQuotaItems(labels, data);
    grid.style.display = "";
    grid.innerHTML = allItems.join("") || '<div class="empty">暫無配額資料</div>';
  }
}

/* ═══════════════════════════════════════════
   模型圖鑑 Tab
   ═══════════════════════════════════════════ */
function _renderHighlights(el, h, cards) {
  el.innerHTML = cards.map(c => {
    const m = h[c.key];
    if (!m) return "";
    const scoreBadge = m.score
      ? `<div class="hl-score-badge" style="background:rgba(49,50,68,0.9);color:${c.color}">${m.score}</div>`
      : "";
    const unconfigured = m.configured === false
      ? `<span style="font-size:0.5rem;color:var(--overlay0);border:1px solid var(--surface1);border-radius:var(--radius-pill);padding:0.05rem 0.3rem;margin-left:0.3rem">未設定</span>`
      : "";
    return `<div class="highlight-card" style="border-left-color:${c.color}${m.configured === false ? ';opacity:0.75' : ''}">
      ${scoreBadge}
      <div class="hl-icon-wrap" style="color:${c.color}">${c.icon}</div>
      <div class="hl-body">
        <div class="hl-label" style="color:${c.color}">${c.label}</div>
        <div class="hl-name">${m.name}${unconfigured}</div>
        <div class="hl-provider">${m.provider}</div>
        <div class="hl-note">${m.note}</div>
      </div>
    </div>`;
  }).join("");
}

async function refreshCatalog() {
  const data = await api("litellm/model-catalog");
  if (!data) return;

  // ── Benchmark highlights ──
  const bmEl = document.getElementById("catalog-benchmark");
  if (bmEl && data.highlights_benchmark) {
    _renderHighlights(bmEl, data.highlights_benchmark, [
      { key: "overall",   icon: ICONS.trophy,     label: "綜合最強",  color: "var(--mauve)" },
      { key: "coding",    icon: ICONS.code,        label: "寫程式",    color: "var(--blue)"  },
      { key: "reasoning", icon: ICONS.calculator,  label: "數學推理",  color: "var(--peach)" },
      { key: "chinese",   icon: ICONS.globe,       label: "中文最強",  color: "var(--red)"   },
      { key: "speed",     icon: ICONS.zap,         label: "出字最快",  color: "var(--yellow)"},
      { key: "cost",      icon: ICONS.coins,       label: "CP 值王",   color: "var(--green)" },
    ]);
  }
  const srcEl = document.getElementById("catalog-sources");
  if (srcEl && data.data_sources) {
    const s = data.data_sources;
    srcEl.textContent = `資料來源：${s.arena} · ${s.swe_bench} · ${s.speed}`;
  }

  // ── Scenario table ──
  const sTbody = document.getElementById("scenario-tbody");
  if (sTbody && data.scenarios) {
    sTbody.innerHTML = data.scenarios.map(s =>
      `<tr>
        <td style="font-weight:600;white-space:nowrap;font-family:var(--font-ui)">${s.task}</td>
        <td><span class="scenario-best-dot"></span><span style="color:var(--blue);font-weight:600">${s.best}</span></td>
        <td style="color:var(--subtext1)">${s.alt}</td>
        <td style="color:var(--subtext0);font-size:0.65rem">${s.reason}</td>
      </tr>`
    ).join("");
  }

  // ── Subjective highlights ──
  const sjEl = document.getElementById("catalog-subjective");
  if (sjEl && data.highlights_subjective) {
    _renderHighlights(sjEl, data.highlights_subjective, [
      { key: "smart", icon: ICONS.brain,    label: "最強",       color: "var(--mauve)" },
      { key: "fast",  icon: ICONS.zap,      label: "最快",       color: "var(--yellow)"},
      { key: "value", icon: ICONS.coins,    label: "CP 值最高",  color: "var(--green)" },
      { key: "free",  icon: ICONS.gift,     label: "免費首選",   color: "var(--teal)"  },
    ]);
  }

  // ── Per-provider catalog table ──
  const tbody = document.getElementById("catalog-tbody");
  if (tbody && data.catalog) {
    tbody.innerHTML = data.catalog.map(row => {
      const cell = (m, accentColor) => `<td class="model-cell">
        <div class="mc-name" style="color:${accentColor}">${m.name}</div>
        <div class="mc-price">${m.price}</div>
        ${m.note ? `<div class="mc-note">${m.note}</div>` : ""}
      </td>`;
      return `<tr>
        <td>${row.provider}</td>
        ${cell(row.smart, "var(--mauve)")}
        ${cell(row.fast,  "var(--yellow)")}
        ${cell(row.value, "var(--green)")}
      </tr>`;
    }).join("");
  }

  // ── Notable unconfigured models ──
  const ucEl = document.getElementById("catalog-unconfigured");
  if (ucEl && data.notable_unconfigured) {
    ucEl.innerHTML = data.notable_unconfigured.map(m => {
      const isConfigured = m.access.includes("已設定");
      const accessColor = isConfigured ? "var(--green)" : "var(--overlay0)";
      return `<div class="highlight-card" style="border-left-color:var(--surface1)">
        <div class="hl-body">
          <div class="hl-name" style="font-size:0.75rem">${m.name}</div>
          <div style="display:flex;align-items:center;gap:0.4rem;margin-top:0.15rem">
            <span class="hl-score-badge" style="position:static;background:var(--surface0);color:var(--lavender)">${m.score}</span>
            <span style="font-size:0.55rem;color:var(--subtext0)">${m.price}</span>
          </div>
          <div class="hl-note" style="margin-top:0.2rem">${m.strengths}</div>
          <div style="font-size:0.5rem;color:${accessColor};margin-top:0.15rem">${m.access}</div>
        </div>
      </div>`;
    }).join("");
  }
}

/* ═══════════════════════════════════════════
   SSE
   ═══════════════════════════════════════════ */
function connectSSE() {
  if (_sse) { _sse.close(); _sse = null; }
  _sse = new EventSource("events/stream");

  _sse.addEventListener("quota", (e) => {
    try { updateQuotaFromSSE(JSON.parse(e.data)); } catch {}
  });

  _sse.addEventListener("usage", (e) => {
    refreshUsage();
  });

  _sse.onerror = () => {
    _sse.close();
    _sse = null;
    setTimeout(() => { if (_autoRefresh) connectSSE(); }, 5000);
  };
}

/* ── Timestamp ── */
function updateTimestamp() {
  const el = document.getElementById("last-updated");
  if (el) el.textContent = "更新: " + new Date().toLocaleTimeString("zh-TW", { hour12: false });
}

/* ═══════════════════════════════════════════
   Init
   ═══════════════════════════════════════════ */
document.addEventListener("DOMContentLoaded", () => {
  // Tab switching
  document.querySelectorAll(".tab-btn").forEach(b => b.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(x => {
      x.classList.remove("active");
      x.setAttribute("aria-selected", "false");
    });
    document.querySelectorAll(".tab-panel").forEach(x => x.classList.remove("active"));
    b.classList.add("active");
    b.setAttribute("aria-selected", "true");
    document.getElementById("panel-" + b.dataset.tab).classList.add("active");
  }));

  // Auto-refresh toggle
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

  // Initial data load
  refreshQuota();
  refreshUsage();
  refreshCatalog();
  updateTimestamp();

  // Start SSE
  connectSSE();

  // Periodic full refresh (every 2 min, SSE supplement)
  setInterval(() => {
    if (!_autoRefresh) return;
    refreshQuota();
    refreshUsage();
    updateTimestamp();
  }, 120000);
});
