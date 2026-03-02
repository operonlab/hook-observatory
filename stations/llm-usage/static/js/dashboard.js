/* LLM Usage Dashboard — vanilla JS + Chart.js */
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
  const fmt = (n, d = 2) => typeof n === 'number' ? '$' + n.toFixed(d) : '—';
  const fmtPct = (n) => typeof n === 'number' ? n.toFixed(1) + '%' : '—';
  const fmtNum = (n) => typeof n === 'number' ? n.toLocaleString() : '—';

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
      // Resize charts when tab becomes visible
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
    $('#updated').textContent = 'Updated: ' + new Date().toLocaleTimeString();
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
    if (subscription) {
      const clis = subscription.clis || [];
      const total = clis.reduce((s, c) => s + (c.monthly_cost_usd || 0), 0);
      $('#sub-total').textContent = fmt(total);
      $('#sub-list').innerHTML = clis.map(c =>
        `<div>${esc(c.name)}: ${fmt(c.monthly_cost_usd)} ${c.active ? '&#10003;' : '&#10007;'}</div>`
      ).join('');
    }

    // Budget card
    if (budget) {
      const pct = budget.used_pct || 0;
      $('#api-spend').textContent = fmt(budget.used_usd);
      const bar = $('#budget-bar');
      bar.style.width = Math.min(pct, 100) + '%';
      bar.className = 'budget-bar' +
        (pct >= 100 ? ' danger' : pct >= budget.warning_threshold_pct ? ' warn' : '');
      $('#budget-detail').textContent =
        `${fmtPct(pct)} of ${fmt(budget.budget_usd)} budget` +
        (budget.over_warning ? ' ⚠️' : '');
    }

    // Total card
    if (summary) {
      const subCost = summary.subscription_total_usd || 0;
      const apiCost = summary.api_month_to_date_usd || 0;
      const total = subCost + apiCost;
      $('#total-cost').textContent = fmt(total);
      const subPct = total > 0 ? (subCost / total * 100).toFixed(0) : 0;
      const apiPct = total > 0 ? (apiCost / total * 100).toFixed(0) : 0;
      $('#total-split').innerHTML =
        `<div>Subscription: ${fmt(subCost)} (${subPct}%)</div>` +
        `<div>API: ${fmt(apiCost)} (${apiPct}%)</div>`;
    }

    // Quota
    renderQuota(subscription);

    // Cache
    if (cache) {
      $('#cache-grid').innerHTML = `
        <div class="cache-item">
          <div class="cache-value">${fmtPct(cache.cache_hit_rate_pct)}</div>
          <div class="cache-label">Cache Hit Rate</div>
        </div>
        <div class="cache-item">
          <div class="cache-value">${fmtNum(cache.cached_tokens)}</div>
          <div class="cache-label">Cached Tokens</div>
        </div>
        <div class="cache-item">
          <div class="cache-value">${fmt(cache.estimated_savings_usd)}</div>
          <div class="cache-label">Est. Savings</div>
        </div>
      `;
    }
  }

  function renderQuota(subscription) {
    const grid = $('#quota-grid');
    if (!subscription) { grid.innerHTML = '<div class="loading">No data</div>'; return; }

    let html = '';
    const clis = subscription.clis || [];
    for (const cli of clis) {
      const quotas = cli.quotas || {};
      for (const [key, q] of Object.entries(quotas)) {
        const pct = q.used_pct || 0;
        const cls = pct >= 90 ? 'critical' : pct >= 70 ? 'high' : '';
        html += `
          <div class="quota-item">
            <div class="quota-label">
              <span>${esc(cli.name)} ${esc(key)}</span>
              <span>${fmtPct(pct)}</span>
            </div>
            <div class="quota-bar-wrap"><div class="quota-bar ${cls}" style="width:${Math.min(pct, 100)}%"></div></div>
          </div>`;
      }
    }

    // Model policy
    const policy = subscription.model_policy || 'normal';
    html += `<div class="quota-item" style="justify-content:center;align-items:center">
      <span class="policy-badge ${esc(policy)}">${esc(policy)}</span>
    </div>`;

    grid.innerHTML = html;
  }

  // ── Render: Trends ──
  function renderTrends(data) {
    if (!data) return;

    const daily = data.daily || [];
    const labels = daily.map(d => d.date?.slice(5) || '');
    const costs = daily.map(d => d.total_cost_usd || 0);
    const ma7 = daily.map(d => d.moving_avg_7d || null);

    // Cumulative
    let cumulative = [];
    let running = 0;
    for (const c of costs) { running += c; cumulative.push(+running.toFixed(4)); }

    // Stats
    const stats = data.stats || {};
    $('#trend-stats').innerHTML = `
      <span class="trend-stat">Total: <strong>${fmt(stats.total_cost_usd)}</strong></span>
      <span class="trend-stat">Avg/day: <strong>${fmt(stats.avg_daily_cost_usd)}</strong></span>
      <span class="trend-stat">Projected: <strong>${fmt(stats.projected_monthly_usd)}</strong></span>
    `;

    // Daily chart
    destroyChart('daily');
    charts.daily = new Chart($('#chart-daily'), {
      type: 'bar',
      data: {
        labels,
        datasets: [
          {
            label: 'Daily Cost',
            data: costs,
            backgroundColor: C.blue + '99',
            borderColor: C.blue,
            borderWidth: 1,
            borderRadius: 3,
            order: 2,
          },
          {
            label: '7d Avg',
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
          label: 'Cumulative',
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

    const models = data.by_model || [];
    const providers = data.by_provider || [];

    // Top 8 models — horizontal bar
    const top8 = models.slice(0, 8);
    destroyChart('byModel');
    charts.byModel = new Chart($('#chart-by-model'), {
      type: 'bar',
      data: {
        labels: top8.map(m => m.model || 'unknown'),
        datasets: [{
          label: 'Cost',
          data: top8.map(m => m.total_cost_usd || 0),
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
      tbody.innerHTML = '<tr><td colspan="7" class="loading">No data</td></tr>';
      return;
    }

    tbody.innerHTML = models.map(m => `
      <tr>
        <td>${esc(m.model || '—')}</td>
        <td>${esc(m.provider || '—')}</td>
        <td class="num">${fmtNum(m.requests)}</td>
        <td class="num">${fmtNum(m.tokens_in)}</td>
        <td class="num">${fmtNum(m.tokens_out)}</td>
        <td class="num">${fmt(m.total_cost_usd)}</td>
        <td class="num">${fmtPct(m.cache_hit_rate)}</td>
      </tr>
    `).join('');
  }

  // Table sort
  $$('th.sortable').forEach(th => {
    th.addEventListener('click', () => {
      // Re-fetch and sort is simpler than local sort for this size
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
