/* LLM 用量儀表板 — vanilla JS + Chart.js */
(function () {
  'use strict';

  // ── Catppuccin Mocha palette for charts ──
  const C = {
    blue: '#89b4fa', lavender: '#b4befe', mauve: '#cba6f7',
    pink: '#f5c2e7', red: '#f38ba8', peach: '#fab387',
    yellow: '#f9e2af', green: '#a6e3a1', teal: '#94e2d5',
    sky: '#89dceb', sapphire: '#74c7ec', overlay0: '#6c7086',
    surface0: '#313244', surface1: '#45475a', text: '#cdd6f4',
    subtext0: '#a6adc8', base: '#1e1e2e', mantle: '#181825',
  };

  const CHART_COLORS = [C.blue, C.mauve, C.peach, C.teal, C.pink, C.yellow, C.green, C.red];

  // Chart.js global defaults
  Chart.defaults.color = C.subtext0;
  Chart.defaults.borderColor = C.surface0;
  Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, 'Inter', sans-serif";
  Chart.defaults.font.size = 12;

  // ── State ──
  let currentDays = 30;
  let charts = {};

  // ── Helpers ──
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);
  const esc = (s) => { const d = document.createElement('div'); d.textContent = String(s ?? ''); return d.innerHTML; };
  const fmt = (n, d = 2) => typeof n === 'number' ? '$' + n.toFixed(d) : '\u2014';
  const fmtPct = (n) => typeof n === 'number' ? n.toFixed(1) + '%' : '\u2014';
  const fmtNum = (n) => typeof n === 'number' ? n.toLocaleString() : '\u2014';

  async function fetchJSON(path) {
    try {
      const r = await fetch(path);
      if (!r.ok) return null;
      return await r.json();
    } catch { return null; }
  }

  // ── Tab switching ──
  $$('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.tab').forEach(t => t.classList.remove('active'));
      $$('.tab-panel').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      const panel = $('#panel-' + btn.dataset.tab);
      if (panel) panel.classList.add('active');
      setTimeout(() => Object.values(charts).forEach(c => c?.resize()), 50);
    });
  });

  // ── Days selector ──
  $$('.day-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.day-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentDays = parseInt(btn.dataset.days, 10);
      loadTrends();
      loadModels();
    });
  });

  // ── Refresh ──
  $('#refresh-btn').addEventListener('click', loadAll);

  // ── Period display ──
  function updatePeriod() {
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, '0');
    $('#period').textContent = `${y}-${m}`;
  }

  function updateTimestamp() {
    $('#updated').textContent = '\u66F4\u65B0\uFF1A' + new Date().toLocaleTimeString();
  }

  // ── Load functions ──
  async function loadAll() {
    updatePeriod();
    await Promise.all([loadOverview(), loadTrends(), loadModels()]);
    updateTimestamp();
  }

  async function loadOverview() {
    const [summary, budget, cache, subscription] = await Promise.all([
      fetchJSON('summary'),
      fetchJSON('budget'),
      fetchJSON('cache'),
      fetchJSON('subscription'),
    ]);
    renderOverview(summary, budget, cache, subscription);
  }

  async function loadTrends() {
    const data = await fetchJSON('trends?days=' + currentDays);
    renderTrends(data);
  }

  async function loadModels() {
    const data = await fetchJSON('by-model?days=' + currentDays);
    renderModels(data);
  }

  // ── Render: Overview ──
  function renderOverview(summary, budget, cache, subscription) {
    // Subscription card
    if (summary && summary.subscription) {
      const sub = summary.subscription;
      $('#sub-total').textContent = fmt(sub.total_monthly_usd);
      const providers = sub.providers || [];
      $('#sub-list').innerHTML = providers.map(p =>
        `<div>${esc(p.cli)}: ${fmt(p.cost_usd)} (${esc(p.plan)})</div>`
      ).join('');
    }

    // Budget card (API spend = ccusage actual)
    if (budget) {
      const pct = budget.used_pct || 0;
      $('#api-spend').textContent = fmt(budget.used_usd);
      const bar = $('#budget-bar');
      bar.style.width = Math.min(pct, 100) + '%';
      bar.className = 'budget-bar' +
        (pct >= 100 ? ' danger' : pct >= budget.warning_threshold_pct ? ' warn' : '');
      $('#budget-detail').textContent =
        `${fmtPct(pct)} / ${fmt(budget.budget_usd)} \u9810\u7B97` +
        (budget.over_warning ? ' \u26A0' : '');
    }

    // Total card
    if (summary && summary.combined) {
      const c = summary.combined;
      $('#total-cost').textContent = fmt(c.total_monthly_usd);
      $('#total-split').innerHTML =
        `<div>\u8A02\u95B1: ${fmt(c.subscription_usd)} (${c.subscription_pct}%)</div>` +
        `<div>API: ${fmt(c.api_usd)} (${c.api_pct}%)</div>`;
    }

    // Quota
    renderQuota(subscription);

    // Cache
    if (cache) {
      $('#cache-grid').innerHTML = `
        <div class="cache-item">
          <div class="cache-value">${fmtPct(cache.cache_hit_rate_pct)}</div>
          <div class="cache-label">\u5FEB\u53D6\u547D\u4E2D\u7387</div>
        </div>
        <div class="cache-item">
          <div class="cache-value">${fmtNum(cache.cached_tokens)}</div>
          <div class="cache-label">\u5FEB\u53D6 Token</div>
        </div>
        <div class="cache-item">
          <div class="cache-value">${fmt(cache.estimated_savings_usd)}</div>
          <div class="cache-label">\u9810\u4F30\u7BC0\u7701</div>
        </div>
      `;
    }
  }

  function renderQuota(subscription) {
    const grid = $('#quota-grid');
    if (!subscription) { grid.innerHTML = '<div class="loading">\u7121\u8CC7\u6599</div>'; return; }

    let html = '';
    const providers = subscription.providers || [];
    for (const p of providers) {
      // Claude Code quotas
      if (p.quota_5h_pct != null) {
        const pct5 = p.quota_5h_pct || 0;
        const cls5 = pct5 >= 90 ? 'critical' : pct5 >= 70 ? 'high' : '';
        html += `
          <div class="quota-item">
            <div class="quota-label">
              <span>${esc(p.cli)} 5h</span>
              <span>${fmtPct(pct5)}</span>
            </div>
            <div class="quota-bar-wrap"><div class="quota-bar ${cls5}" style="width:${Math.min(pct5, 100)}%"></div></div>
          </div>`;
      }
      if (p.quota_7d_pct != null) {
        const pct7 = p.quota_7d_pct || 0;
        const cls7 = pct7 >= 90 ? 'critical' : pct7 >= 70 ? 'high' : '';
        html += `
          <div class="quota-item">
            <div class="quota-label">
              <span>${esc(p.cli)} 7d</span>
              <span>${fmtPct(pct7)}</span>
            </div>
            <div class="quota-bar-wrap"><div class="quota-bar ${cls7}" style="width:${Math.min(pct7, 100)}%"></div></div>
          </div>`;
      }
    }

    // Model policy
    const cc = providers.find(p => p.cli === 'claude-code');
    const mode = cc?.current_mode || '\u6B63\u5E38';
    const modeLabel = mode === 'boost' ? 'BOOST' : '\u6B63\u5E38';
    html += `<div class="quota-item" style="justify-content:center;align-items:center">
      <span class="policy-badge ${esc(mode)}">${esc(modeLabel)}</span>
    </div>`;

    grid.innerHTML = html || '<div class="loading">\u7121\u8CC7\u6599</div>';
  }

  // ── Render: Trends ──
  function renderTrends(data) {
    if (!data) return;

    const daily = data.daily || [];
    const labels = daily.map(d => d.date?.slice(5) || '');
    const costs = daily.map(d => d.cost_usd || 0);
    const ma7 = daily.map(d => d.cost_7d_avg_usd || null);
    const cumulative = daily.map(d => d.cumulative_cost_usd || 0);

    // Stats
    const stats = data.summary || {};
    $('#trend-stats').innerHTML = `
      <span class="trend-stat">\u5408\u8A08: <strong>${fmt(stats.total_cost_usd)}</strong></span>
      <span class="trend-stat">\u65E5\u5747: <strong>${fmt(stats.avg_daily_cost_usd)}</strong></span>
      <span class="trend-stat">\u6708\u63A8\u4F30: <strong>${fmt(stats.projected_monthly_usd)}</strong></span>
    `;

    // Daily chart
    destroyChart('daily');
    charts.daily = new Chart($('#chart-daily'), {
      type: 'bar',
      data: {
        labels,
        datasets: [
          {
            label: '\u6BCF\u65E5\u82B1\u8CBB',
            data: costs,
            backgroundColor: C.blue + '99',
            borderColor: C.blue,
            borderWidth: 1,
            borderRadius: 3,
            order: 2,
          },
          {
            label: '7\u65E5\u5747\u7DDA',
            data: ma7,
            type: 'line',
            borderColor: C.peach,
            backgroundColor: 'transparent',
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.3,
            order: 1,
          },
        ],
      },
      options: chartOpts('$'),
    });

    // Cumulative chart
    destroyChart('cumulative');
    charts.cumulative = new Chart($('#chart-cumulative'), {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: '\u7D2F\u8A08',
          data: cumulative,
          borderColor: C.teal,
          backgroundColor: C.teal + '20',
          fill: true,
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.3,
        }],
      },
      options: chartOpts('$'),
    });
  }

  // ── Render: Models ──
  function renderModels(data) {
    if (!data) return;

    const models = data.models || [];
    const providers = data.by_provider || [];

    // Top 8 models — horizontal bar
    const top8 = models.slice(0, 8);
    destroyChart('byModel');
    charts.byModel = new Chart($('#chart-by-model'), {
      type: 'bar',
      data: {
        labels: top8.map(m => m.model || 'unknown'),
        datasets: [{
          label: '\u82B1\u8CBB',
          data: top8.map(m => m.cost_usd || 0),
          backgroundColor: CHART_COLORS.slice(0, top8.length),
          borderRadius: 4,
        }],
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { color: C.surface0 }, ticks: { callback: v => '$' + v } },
          y: { grid: { display: false } },
        },
      },
    });

    // Provider donut
    destroyChart('byProvider');
    charts.byProvider = new Chart($('#chart-by-provider'), {
      type: 'doughnut',
      data: {
        labels: providers.map(p => p.provider || 'unknown'),
        datasets: [{
          data: providers.map(p => p.total_cost_usd || 0),
          backgroundColor: [C.mauve, C.blue, C.peach, C.green, C.pink],
          borderColor: C.mantle,
          borderWidth: 2,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: 'bottom', labels: { padding: 16 } },
        },
      },
    });

    // Model table
    renderModelTable(models);
  }

  function renderModelTable(models) {
    const tbody = $('#model-tbody');
    if (!models || models.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" class="loading">\u7121\u8CC7\u6599</td></tr>';
      return;
    }

    tbody.innerHTML = models.map(m => `
      <tr>
        <td>${esc(m.model || '\u2014')}</td>
        <td>${esc(m.provider || '\u2014')}</td>
        <td class="num">${fmtNum(m.requests)}</td>
        <td class="num">${fmtNum(m.tokens_in)}</td>
        <td class="num">${fmtNum(m.tokens_out)}</td>
        <td class="num">${fmt(m.cost_usd)}</td>
        <td class="num">${fmtPct(m.cache_hit_rate)}</td>
      </tr>
    `).join('');
  }

  // Table sort
  $$('th.sortable').forEach(th => {
    th.addEventListener('click', () => {
      loadModels();
    });
  });

  // ── Chart helpers ──
  function chartOpts(prefix) {
    return {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { intersect: false, mode: 'index' },
      plugins: {
        legend: { labels: { usePointStyle: true, padding: 12 } },
        tooltip: {
          callbacks: {
            label: ctx => {
              const v = ctx.parsed.y ?? ctx.parsed.x ?? ctx.raw;
              return ctx.dataset.label + ': ' + prefix + (typeof v === 'number' ? v.toFixed(4) : v);
            },
          },
        },
      },
      scales: {
        x: { grid: { color: C.surface0 } },
        y: { grid: { color: C.surface0 }, ticks: { callback: v => prefix + v } },
      },
    };
  }

  function destroyChart(key) {
    if (charts[key]) { charts[key].destroy(); charts[key] = null; }
  }

  // ── Init ──
  loadAll();
})();
