/**
 * metrics.js — System metrics + LLM usage rendering
 *
 * LLM groups are rendered dynamically from backend `llm` dict.
 * Provider/metric labels have known mappings with uppercase fallback,
 * so new providers or metrics from agent-metrics appear automatically.
 */

(function() {
  const tmuxStatusEl = document.getElementById('tmux-status');

  // Display labels — unknown keys fall back to UPPERCASED key
  const PROVIDER_LABELS = { cc: 'CLAUDE', cx: 'CODEX', gm: 'GEMINI' };
  const METRIC_LABELS = { '5h': '5H', '7d': '7D', 'ex': 'EX', 'pro': 'Pro', 'flash': 'Flash' };
  // Render order: providers first, then metrics within each provider; unknowns appended
  const PROVIDER_ORDER = ['cc', 'cx', 'gm'];
  const METRIC_ORDER = ['flash', '5h', '7d', 'ex', 'pro'];

  function renderMetrics(m) {
    if (!m) { tmuxStatusEl.style.display = 'none'; return; }
    tmuxStatusEl.style.display = '';
    const sep = '<span class="ms-sep">|</span>';
    const parts = [];

    // System metrics
    if (m.net) parts.push(`<span class="ms-net"><span class="ms-label">NET</span><span class="ms-val">${escHtml(m.net)}</span></span>`);
    if (m.cpu) parts.push(`<span class="ms-cpu"><span class="ms-label">CPU</span><span class="ms-val">${escHtml(m.cpu)}</span></span>`);
    if (m.mem) parts.push(`<span class="ms-mem"><span class="ms-label">MEM</span><span class="ms-val">${escHtml(m.mem)}</span></span>`);
    if (m.disk) parts.push(`<span class="ms-disk"><span class="ms-label">DISK</span><span class="ms-val">${escHtml(m.disk)}</span></span>`);

    // LLM Usage — dynamic rendering
    if (m.llm && typeof m.llm === 'object') {
      const providers = Object.keys(m.llm);
      providers.sort((a, b) => {
        const ia = PROVIDER_ORDER.indexOf(a), ib = PROVIDER_ORDER.indexOf(b);
        if (ia >= 0 && ib >= 0) return ia - ib;
        if (ia >= 0) return -1;
        if (ib >= 0) return 1;
        return a.localeCompare(b);
      });

      for (const provider of providers) {
        const metrics = m.llm[provider];
        if (!metrics || typeof metrics !== 'object') continue;
        const entries = Object.entries(metrics).filter(([k, v]) => {
          if (!v || v === '?') return false;
          // Claude Ex: 餘額為零時不顯示
          if (provider === 'cc' && k === 'ex' && v === '0%') return false;
          return true;
        });
        if (!entries.length) continue;
        entries.sort((a, b) => {
          const ia = METRIC_ORDER.indexOf(a[0]), ib = METRIC_ORDER.indexOf(b[0]);
          if (ia >= 0 && ib >= 0) return ia - ib;
          if (ia >= 0) return -1;
          if (ib >= 0) return 1;
          return a[0].localeCompare(b[0]);
        });

        const label = PROVIDER_LABELS[provider] || provider.toUpperCase();
        let g = `<span class="usage-group" data-provider="${escHtml(provider)}"><span class="usage-group-label">${escHtml(label)}</span>`;
        for (const [metric, value] of entries) {
          const mLabel = METRIC_LABELS[metric] || metric.toUpperCase();
          g += `<span class="ms-llm ms-${escHtml(provider)}-${escHtml(metric)}"><span class="ms-label">${escHtml(mLabel)}</span><span class="ms-val">${escHtml(value)}</span></span>`;
        }
        g += '</span>';
        parts.push(g);
      }
    }

    tmuxStatusEl.innerHTML = parts.join(sep);
  }

  // Expose
  window.renderMetrics = renderMetrics;
})();
