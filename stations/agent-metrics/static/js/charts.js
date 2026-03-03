/* charts.js — Pure SVG gauge rings + sparklines (zero dependencies) */

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
  const offset = 100 - clamped;
  circle.setAttribute('stroke-dashoffset', offset);

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
    const y = height - ((v - min) / range) * (height - 4) - 2;
    return `${x},${y}`;
  });

  const pathD = 'M' + points.join(' L');

  let fillPath = '';
  if (opts.fill) {
    fillPath = `<path d="${pathD} L${width},${height} L0,${height} Z"
      fill="${color}" fill-opacity="0.1" stroke="none"/>`;
  }

  container.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
      ${fillPath}
      <path d="${pathD}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round"/>
    </svg>
  `;
}

/**
 * Create a progress bar element.
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
