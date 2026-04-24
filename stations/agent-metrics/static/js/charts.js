/* charts.js — Pure SVG gauge rings + sparklines (Mission Control Edition) */

/**
 * Set a gauge ring's value. Expects SVG structure with .fill circle.
 * @param {string} gaugeId - ID of the .fill circle element
 * @param {number} pct - 0-100 percentage
 * @param {string} valueId - ID of the value display element
 * @param {string} [detailId] - ID of the detail text element
 * @param {string} [detailText] - Detail text to show
 */
function setGauge(gaugeId, pct, valueId, detailId, detailText) {
  const circle = document.getElementById(gaugeId);
  const valueEl = document.getElementById(valueId);
  if (!circle || !valueEl) return;

  const clamped = Math.max(0, Math.min(100, pct));

  // Use stroke-dasharray/offset on a circle with circumference ~100
  // (viewBox 36x36, r=15.9 → circ ≈ 99.9)
  circle.setAttribute('stroke-dasharray', `${clamped}, 100`);
  circle.setAttribute('stroke-dashoffset', '0');

  valueEl.textContent = Math.round(clamped) + '%';

  // Color thresholds
  const container = circle.closest('.gauge-ring');
  if (container) {
    container.classList.remove('gauge-ok', 'gauge-warn', 'gauge-crit');
    if (clamped < 60) container.classList.add('gauge-ok');
    else if (clamped < 85) container.classList.add('gauge-warn');
    else container.classList.add('gauge-crit');
  }

  if (detailId && detailText) {
    const detailEl = document.getElementById(detailId);
    if (detailEl) detailEl.textContent = detailText;
  }
}

/**
 * Render a sparkline SVG into a container.
 * @param {HTMLElement} container - Container element
 * @param {number[]} data - Data points
 * @param {object} [opts] - Options
 * @param {string} [opts.color] - Stroke color
 * @param {boolean} [opts.fill] - Whether to fill under the line
 * @param {number} [opts.height] - SVG height
 */
function renderSparkline(container, data, opts = {}) {
  if (!container || !data || data.length < 2) {
    container.innerHTML = '<div class="empty">No data</div>';
    return;
  }

  const color = opts.color || '#89b4fa';
  const height = opts.height || 60;
  const width = container.clientWidth || 300;

  const max = Math.max(...data) || 1;
  const min = Math.min(...data);
  const range = max - min || 1;

  const points = data.map((v, i) => {
    const x = (i / (data.length - 1)) * width;
    const y = height - ((v - min) / range) * (height - 6) - 3;
    return `${x},${y}`;
  });

  const pathD = 'M' + points.join(' L');

  let fillPath = '';
  if (opts.fill) {
    fillPath = `<path d="${pathD} L${width},${height} L0,${height} Z"
      fill="${color}" fill-opacity="0.08" stroke="none"/>`;
  }

  container.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" style="overflow:visible">
      <defs>
        <filter id="spark-glow">
          <feGaussianBlur stdDeviation="1.5" result="blur"/>
          <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
      </defs>
      ${fillPath}
      <path d="${pathD}" fill="none" stroke="${color}" stroke-width="1.5"
        stroke-linejoin="round" stroke-linecap="round"
        filter="url(#spark-glow)" opacity="0.9"/>
    </svg>
  `;
}

/**
 * Create a progress bar element with gradient fill.
 * @param {number} pct - 0-100
 * @param {string} leftText - Left label
 * @param {string} rightText - Right label
 * @returns {string} HTML string
 */
function progressBar(pct, leftText, rightText) {
  const clamped = Math.max(0, Math.min(100, pct));
  let cls = '';
  if (clamped >= 90) cls = 'crit';
  else if (clamped >= 70) cls = 'warn';

  return `
    <div class="progress-wrap">
      <div class="progress-track">
        <div class="progress-fill ${cls}" style="width:${clamped}%"></div>
      </div>
      <div class="progress-label">
        <span>${leftText}</span>
        <span>${rightText}</span>
      </div>
    </div>
  `;
}

/**
 * Build a gauge card HTML string for the quota grid.
 * @param {string} label - Display label
 * @param {number|null} pct - Percentage 0-100 or null
 * @param {string} displayVal - Value to show inside ring
 * @param {string} fullVal - Full tooltip value
 * @returns {string} HTML string
 */
function buildGaugeCard(label, pct, displayVal, fullVal, resetCaption) {
  let colorVar = 'var(--green)';
  let threshClass = 'gauge-ok';
  if (pct !== null) {
    if (pct >= 85)      { colorVar = 'var(--red)';    threshClass = 'gauge-crit'; }
    else if (pct >= 60) { colorVar = 'var(--yellow)'; threshClass = 'gauge-warn'; }
  }
  const dashArray = pct !== null ? pct : 0;

  const resetHtml = resetCaption
    ? `<div class="quota-reset">${resetCaption}</div>`
    : '';

  return `<div class="quota-card" title="${fullVal}">
    <div class="quota-label">${label}</div>
    <div class="gauge-container">
      <div class="gauge-ring ${threshClass}">
        <svg viewBox="0 0 36 36">
          <circle class="track" cx="18" cy="18" r="15.9"/>
          <circle class="fill" cx="18" cy="18" r="15.9"
            stroke-dasharray="${dashArray}, 100"
            stroke-dashoffset="0"/>
        </svg>
        <div class="gauge-value">${displayVal}</div>
      </div>
    </div>
    ${resetHtml}
  </div>`;
}

/**
 * Format an ISO-8601 resets_at timestamp into a compact local string +
 * relative countdown suitable for the quota card caption.
 * Returns "" when the input is falsy / invalid.
 */
function formatResetCaption(iso) {
  if (!iso) return '';
  const dt = new Date(iso);
  if (isNaN(dt.getTime())) return '';
  const now = new Date();
  const diffMs = dt.getTime() - now.getTime();
  const absH = Math.abs(diffMs) / 3_600_000;
  let rel;
  if (absH < 1) {
    const m = Math.round(absH * 60);
    rel = diffMs >= 0 ? `in ${m}m` : `${m}m ago`;
  } else if (absH < 48) {
    rel = diffMs >= 0 ? `in ${absH.toFixed(1)}h` : `${absH.toFixed(1)}h ago`;
  } else {
    const d = absH / 24;
    rel = diffMs >= 0 ? `in ${d.toFixed(1)}d` : `${d.toFixed(1)}d ago`;
  }
  const mm = String(dt.getMonth() + 1).padStart(2, '0');
  const dd = String(dt.getDate()).padStart(2, '0');
  const hh = String(dt.getHours()).padStart(2, '0');
  const mi = String(dt.getMinutes()).padStart(2, '0');
  return `reset ${mm}-${dd} ${hh}:${mi} · ${rel}`;
}
