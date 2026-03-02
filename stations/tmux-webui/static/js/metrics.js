/**
 * metrics.js — System metrics + LLM usage rendering
 */

(function() {
  const tmuxStatusEl = document.getElementById('tmux-status');

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

    // Claude Usage
    const hasClaude = m.claude_5h || m.claude_7d || m.claude_ex;
    if (hasClaude) {
      let cg = '<span class="usage-group"><span class="usage-group-label">CLAUDE</span>';
      if (m.claude_5h) cg += `<span class="ms-c5h"><span class="ms-label">5H</span><span class="ms-val">${escHtml(m.claude_5h)}</span></span>`;
      if (m.claude_7d) cg += `<span class="ms-c7d"><span class="ms-label">7D</span><span class="ms-val">${escHtml(m.claude_7d)}</span></span>`;
      if (m.claude_ex) cg += `<span class="ms-cex"><span class="ms-label">EX</span><span class="ms-val">${escHtml(m.claude_ex)}</span></span>`;
      cg += '</span>';
      parts.push(cg);
    }

    // Codex Usage
    const hasCodex = (m.codex_5h && m.codex_5h !== '?') || (m.codex_7d && m.codex_7d !== '?');
    if (hasCodex) {
      let xg = '<span class="usage-group"><span class="usage-group-label">CODEX</span>';
      if (m.codex_5h && m.codex_5h !== '?') xg += `<span class="ms-x5h"><span class="ms-label">5H</span><span class="ms-val">${escHtml(m.codex_5h)}</span></span>`;
      if (m.codex_7d && m.codex_7d !== '?') xg += `<span class="ms-x7d"><span class="ms-label">7D</span><span class="ms-val">${escHtml(m.codex_7d)}</span></span>`;
      xg += '</span>';
      parts.push(xg);
    }

    // Gemini Usage
    const hasGemini = m.gemini_pro && m.gemini_pro !== '?';
    if (hasGemini) {
      let gg = '<span class="usage-group"><span class="usage-group-label">GEMINI</span>';
      gg += `<span class="ms-gp"><span class="ms-label">Pro</span><span class="ms-val">${escHtml(m.gemini_pro)}</span></span>`;
      gg += '</span>';
      parts.push(gg);
    }

    tmuxStatusEl.innerHTML = parts.join(sep);
  }

  // Expose
  window.renderMetrics = renderMetrics;
})();
