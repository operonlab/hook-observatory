/**
 * app.js — Main application logic for tmux-webui V2
 * Orchestrates WebSocket, pane management, layout, tool profiles, skills
 */

// ========================================================================
// 0. Utilities
// ========================================================================
function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// ========================================================================
// 1. State
// ========================================================================
window.tmuxState = {
  focusedPane: '',
  maximizedPane: '',
  paneEls: {},
  paneInfo: {},
  paneOrder: [],
  currentLayout: 'auto',
  customWeights: null,
  currentTool: null,
  skillPaletteOpen: false,
  currentSession: '',
  activeWindowIdx: null,
};

// ========================================================================
// 2. DOM Refs
// ========================================================================
const container     = document.getElementById('pane-container');
const sessionsEl    = document.getElementById('sessions');
const connectBtn    = document.getElementById('connect-btn');
const refreshBtn    = document.getElementById('refresh-btn');
const statusEl      = document.getElementById('status');
const inputEl       = document.getElementById('input');
const sendBtn       = document.getElementById('send-btn');
const focusLabel    = document.getElementById('focused-label');
const layoutSelect  = document.getElementById('layout-select');
const resetLayoutBtn = document.getElementById('reset-layout');
const toolActionsEl = document.getElementById('tool-actions');
const skillPalette  = document.getElementById('skill-palette');
const skillSearchEl = document.getElementById('skill-search');
const skillCatsEl   = document.getElementById('skill-categories');
const winTabsEl     = document.getElementById('win-tabs');
const mobilePaneTabs = document.getElementById('mobile-pane-tabs');

const S = window.tmuxState;

// ========================================================================
// 3. Tool Profiles
// ========================================================================
const TOOL_PROFILES = {
  claude: {
    name: 'Claude Code',
    detect: (cmd, title) => /claude/i.test(cmd) || /claude/i.test(title) || /^\d+\.\d+\.\d+$/.test(cmd),
    actions: [
      {l:'/compact',s:'/compact'},{l:'/clear',s:'/clear'},{l:'/cost',s:'/cost'},
      {l:'/model',s:'/model'},{l:'/commit',s:'/commit'},{l:'/review',s:'/review'},
      {l:'/plan',s:'/plan'},{l:'/status',s:'/status'},{l:'/context',s:'/context'},
      {l:'/think',s:'/think'},{l:'/help',s:'/help'},
    ],
  },
  codex: {
    name: 'Codex CLI',
    detect: (cmd, title) => /codex/i.test(cmd) || /codex/i.test(title),
    actions: [
      {l:'/compact',s:'/compact'},{l:'/diff',s:'/diff'},{l:'/model',s:'/model'},
      {l:'/review',s:'/review'},{l:'/status',s:'/status'},{l:'/plan',s:'/plan'},
      {l:'/new',s:'/new'},{l:'/mention',s:'/mention '},
    ],
  },
  gemini: {
    name: 'Gemini CLI',
    detect: (cmd, title) => /gemini/i.test(cmd) || /gemini/i.test(title),
    actions: [
      {l:'/compress',s:'/compress'},{l:'/clear',s:'/clear'},{l:'/stats',s:'/stats'},
      {l:'/copy',s:'/copy'},{l:'/tools',s:'/tools'},{l:'/mcp',s:'/mcp'},
      {l:'/memory',s:'/memory show'},{l:'/help',s:'/help'},
    ],
  },
  aider: {
    name: 'Aider',
    detect: (cmd, title) => /aider/i.test(cmd) || /aider/i.test(title),
    actions: [
      {l:'/add',s:'/add '},{l:'/drop',s:'/drop '},{l:'/diff',s:'/diff'},
      {l:'/undo',s:'/undo'},{l:'/commit',s:'/commit'},{l:'/model',s:'/model '},
      {l:'/tokens',s:'/tokens'},{l:'/ask',s:'/ask '},{l:'/help',s:'/help'},
    ],
  },
  cursor: {
    name: 'Cursor',
    detect: (cmd, title) => /cursor/i.test(cmd) || /cursor/i.test(title),
    actions: [
      {l:'/compress',s:'/compress'},{l:'/model',s:'/model'},
      {l:'/rules',s:'/rules'},{l:'/mcp',s:'/mcp'},
    ],
  },
};
const PROFILE_ORDER = ['claude','codex','gemini','aider','cursor'];

function detectTool(pane) {
  if (!pane) return null;
  for (const key of PROFILE_ORDER) {
    if (TOOL_PROFILES[key].detect(pane.command || '', pane.title || '')) return key;
  }
  return null;
}

// ========================================================================
// 4. Skill Catalog
// ========================================================================
const SKILL_CATEGORIES = [
  {key:'search',label:'Search & Research'},{key:'visual',label:'Visual & Design'},
  {key:'document',label:'Documents & Files'},{key:'writing',label:'Writing & Content'},
  {key:'devtools',label:'Dev & Engineering'},{key:'orchestr',label:'Orchestration'},
  {key:'skillmgmt',label:'Skill Management'},{key:'notebook',label:'Notebooks'},
  {key:'infra',label:'Infra & Config'},
];

const SKILL_CATALOG = [
  {c:'search',l:'smart-search',h:1},{c:'search',l:'brainstorming',h:1},
  {c:'search',l:'competitive-intel',h:1},{c:'search',l:'model-mentor',h:1},
  {c:'search',l:'meeting-insights',h:1},
  {c:'visual',l:'diagram-gen',h:1},{c:'visual',l:'image-gen',h:1},
  {c:'visual',l:'image-edit',h:1},{c:'visual',l:'image-prompt',h:1},
  {c:'visual',l:'canvas-design',h:1},{c:'visual',l:'frontend-design',h:1},
  {c:'visual',l:'theme-factory',h:1},{c:'visual',l:'brand-guidelines',h:1},
  {c:'visual',l:'ui-audit',h:0},
  {c:'document',l:'pdf',h:1},{c:'document',l:'xlsx',h:1},
  {c:'document',l:'pptx',h:1},{c:'document',l:'docx',h:1},{c:'document',l:'ocr',h:0},
  {c:'writing',l:'content-writer',h:1},{c:'writing',l:'marketing-copy',h:1},
  {c:'writing',l:'doc-coauthoring',h:1},{c:'writing',l:'readme-gen',h:0},
  {c:'writing',l:'changelog-gen',h:0},
  {c:'devtools',l:'systematic-debugging',h:1},{c:'devtools',l:'tdd',h:1},
  {c:'devtools',l:'verification-before-completion',h:0},{c:'devtools',l:'spec-kit',h:1},
  {c:'devtools',l:'mcp-builder',h:1},{c:'devtools',l:'git-worktrees',h:1},
  {c:'orchestr',l:'maestro',h:1},{c:'orchestr',l:'team-tasks',h:1},
  {c:'orchestr',l:'claude-code-headless',h:1},{c:'orchestr',l:'codex-headless',h:1},
  {c:'orchestr',l:'gemini-cli-headless',h:1},{c:'orchestr',l:'scheduler',h:1},
  {c:'skillmgmt',l:'create-skill',h:1},{c:'skillmgmt',l:'skill-optimizer',h:1},
  {c:'skillmgmt',l:'skill-publisher',h:1},{c:'skillmgmt',l:'skill-catalog',h:0},
  {c:'skillmgmt',l:'skill-tester',h:1},
  {c:'notebook',l:'notebookllm',h:1},{c:'notebook',l:'notebookllm-visual',h:1},
  {c:'infra',l:'sync-config',h:1},{c:'infra',l:'keybindings-help',h:0},
];

// ========================================================================
// 5. Layout Presets
// ========================================================================
const LAYOUT_PRESETS = {
  '2x2':  { cols:[1,1], rows:[1,1] },
  '4col': { cols:[1,1,1,1], rows:[1] },
  auto:   { cols:null, rows:null },
  '1+2':  { cols:[2,1], rows:[1,1],
             placement:[{c:'1/2',r:'1/3'},{c:'2/3',r:'1/2'},{c:'2/3',r:'2/3'}] },
  '3col': { cols:[1,1,1], rows:[1] },
  '1x1':  { cols:[1], rows:[1] },
};

// ========================================================================
// 6. Helpers
// ========================================================================

window.sendSkillOrAction = function(cmdStr) {
  if (!window.tmuxWs || !window.tmuxWs.isConnected() || !S.focusedPane) return;
  if (cmdStr.endsWith(' ')) {
    inputEl.value = cmdStr;
    inputEl.focus();
  } else {
    window.tmuxWs.send({ type:'input', pane:S.focusedPane, text:cmdStr });
    if (S.paneEls[S.focusedPane]) S.paneEls[S.focusedPane].resetScroll();
  }
};

window.flashInputError = function(msg) {
  inputEl.classList.add('input-error');
  inputEl.placeholder = msg || 'Send failed';
  setTimeout(() => {
    inputEl.classList.remove('input-error');
    inputEl.placeholder = 'Type a message...';
  }, 1500);
};

window.sendInput = function() {
  const text = inputEl.value;
  if (!text) return;
  if (!window.tmuxWs || !window.tmuxWs.isConnected()) { window.flashInputError('Not connected'); return; }
  if (!S.focusedPane) { window.flashInputError('No pane selected'); return; }
  window.tmuxWs.send({ type:'input', pane:S.focusedPane, text });
  inputEl.value = '';
  inputEl.style.height = 'auto';
  if (S.paneEls[S.focusedPane]) S.paneEls[S.focusedPane].resetScroll();
};

sendBtn.addEventListener('click', () => { window.acClose?.(); window.sendInput(); });

// ========================================================================
// 7. Tool Actions / Skill Palette
// ========================================================================

function renderToolActions(toolKey) {
  // Tool actions disabled — slash command buttons not needed
  S.currentTool = toolKey;
  toolActionsEl.innerHTML = '';
}

function updateSkillsVisibility(toolKey) {
  // Skill palette removed from DOM — no-op
}

function renderSkillPalette(filter) {
  const lf = (filter || '').toLowerCase();
  skillCatsEl.innerHTML = '';
  for (const cat of SKILL_CATEGORIES) {
    const skills = SKILL_CATALOG.filter(sk => sk.c === cat.key && (!lf || sk.l.includes(lf)));
    if (skills.length === 0) continue;
    const hdr = document.createElement('div');
    hdr.className = 'skill-cat-header';
    hdr.innerHTML = `<span class="arrow">\u25BC</span> ${cat.label} <span style="opacity:.4">(${skills.length})</span>`;
    const body = document.createElement('div');
    body.className = 'skill-cat-body';
    hdr.addEventListener('click', () => { hdr.classList.toggle('collapsed'); body.classList.toggle('collapsed'); });
    for (const sk of skills) {
      const btn = document.createElement('button');
      btn.className = 'sbtn';
      btn.textContent = '/' + sk.l;
      btn.addEventListener('click', () => window.sendSkillOrAction('/' + sk.l + (sk.h ? ' ' : '')));
      body.appendChild(btn);
    }
    skillCatsEl.appendChild(hdr);
    skillCatsEl.appendChild(body);
  }
}

if (skillSearchEl) skillSearchEl.addEventListener('input', () => renderSkillPalette(skillSearchEl.value));

// ========================================================================
// 8. Layout Engine
// ========================================================================

function applyLayout() {
  const ordered = S.paneOrder.length ? S.paneOrder.filter(id => S.paneEls[id]) : Object.keys(S.paneEls);
  const count = ordered.length;
  if (count === 0) return;
  container.style.display = 'grid';

  ordered.forEach(id => {
    if (S.paneEls[id]) {
      S.paneEls[id].box.style.gridColumn = '';
      S.paneEls[id].box.style.gridRow = '';
      S.paneEls[id].box.style.display = '';
    }
  });
  container.querySelectorAll('.hidden-indicator').forEach(el => el.remove());

  if (S.currentLayout === 'auto') {
    if (count <= 1) { container.style.gridTemplateColumns = '1fr'; container.style.gridTemplateRows = '1fr'; }
    else if (count === 2) { container.style.gridTemplateColumns = '1fr 1fr'; container.style.gridTemplateRows = '1fr'; }
    else if (count <= 4) { container.style.gridTemplateColumns = '1fr 1fr'; container.style.gridTemplateRows = '1fr 1fr'; }
    else if (count <= 6) { container.style.gridTemplateColumns = '1fr 1fr 1fr'; container.style.gridTemplateRows = '1fr 1fr'; }
    else { container.style.gridTemplateColumns = '1fr 1fr 1fr'; container.style.gridTemplateRows = `repeat(${Math.ceil(count/3)}, 1fr)`; }
  } else {
    const preset = LAYOUT_PRESETS[S.currentLayout];
    if (!preset || !preset.cols) return;
    const cols = S.customWeights ? S.customWeights.cols : preset.cols;
    const rows = S.customWeights ? S.customWeights.rows : preset.rows;
    const slots = cols.length * rows.length;
    container.style.gridTemplateColumns = cols.map(v => v + 'fr').join(' ');
    container.style.gridTemplateRows = rows.map(v => v + 'fr').join(' ');

    if (count > slots && !preset.placement) {
      for (let i = slots; i < ordered.length; i++) {
        if (S.paneEls[ordered[i]]) S.paneEls[ordered[i]].box.style.display = 'none';
      }
      const badge = document.createElement('div');
      badge.className = 'hidden-indicator';
      badge.textContent = `+${count - slots} hidden`;
      badge.addEventListener('click', () => { layoutSelect.value = 'auto'; S.currentLayout = 'auto'; S.customWeights = null; applyLayout(); saveLayoutPref(); });
      container.appendChild(badge);
    }
    if (preset.placement) {
      ordered.forEach((id, i) => {
        const p = preset.placement[i];
        if (p && S.paneEls[id]) { S.paneEls[id].box.style.gridColumn = p.c; S.paneEls[id].box.style.gridRow = p.r; }
      });
    }
  }

  rebuildResizeHandles();
  updateMobilePaneTabs();
  if (window._fitAllPanes) window._fitAllPanes();
}

// ── Resize handles (identical logic to V1) ──

function getCurrentFr() {
  if (S.currentLayout === 'auto') return null;
  const preset = LAYOUT_PRESETS[S.currentLayout];
  if (!preset || !preset.cols) return null;
  return {
    cols: S.customWeights ? [...S.customWeights.cols] : [...preset.cols],
    rows: S.customWeights ? [...S.customWeights.rows] : [...preset.rows],
  };
}

function rebuildResizeHandles() {
  container.querySelectorAll('.resize-handle').forEach(h => h.remove());
  if (S.maximizedPane || S.currentLayout === 'auto') return;
  const fr = getCurrentFr();
  if (!fr) return;
  if (fr.cols.length > 1) {
    const total = fr.cols.reduce((s,v) => s+v, 0);
    let acc = 0;
    for (let i = 0; i < fr.cols.length - 1; i++) {
      acc += fr.cols[i];
      const h = document.createElement('div');
      h.className = 'resize-handle resize-handle-col';
      h.style.left = ((acc/total)*100) + '%';
      container.appendChild(h);
      initColResize(h, i);
    }
  }
  if (fr.rows.length > 1) {
    const total = fr.rows.reduce((s,v) => s+v, 0);
    let acc = 0;
    for (let i = 0; i < fr.rows.length - 1; i++) {
      acc += fr.rows[i];
      const h = document.createElement('div');
      h.className = 'resize-handle resize-handle-row';
      h.style.top = ((acc/total)*100) + '%';
      container.appendChild(h);
      initRowResize(h, i);
    }
  }
}

function ensureCustomWeights() {
  if (S.customWeights) return;
  const preset = LAYOUT_PRESETS[S.currentLayout];
  if (!preset || !preset.cols) return;
  S.customWeights = { cols:[...preset.cols], rows:[...preset.rows] };
}

function repositionHandles() {
  const fr = getCurrentFr();
  if (!fr) return;
  let ci = 0;
  const colHandles = container.querySelectorAll('.resize-handle-col');
  if (fr.cols.length > 1) {
    const total = fr.cols.reduce((s,v) => s+v, 0);
    let acc = 0;
    for (let i = 0; i < fr.cols.length - 1; i++) { acc += fr.cols[i]; if (colHandles[ci]) colHandles[ci].style.left = ((acc/total)*100)+'%'; ci++; }
  }
  let ri = 0;
  const rowHandles = container.querySelectorAll('.resize-handle-row');
  if (fr.rows.length > 1) {
    const total = fr.rows.reduce((s,v) => s+v, 0);
    let acc = 0;
    for (let i = 0; i < fr.rows.length - 1; i++) { acc += fr.rows[i]; if (rowHandles[ri]) rowHandles[ri].style.top = ((acc/total)*100)+'%'; ri++; }
  }
}

function initColResize(handle, idx) {
  handle.addEventListener('pointerdown', (e) => {
    e.preventDefault(); handle.setPointerCapture(e.pointerId); handle.classList.add('active');
    ensureCustomWeights();
    const startX = e.clientX, cw = S.customWeights.cols;
    const totalFr = cw.reduce((s,v) => s+v, 0), frToPx = container.clientWidth / totalFr;
    const startL = cw[idx], startR = cw[idx+1];
    function onMove(ev) { const dx = ev.clientX - startX, dFr = dx/frToPx; cw[idx] = Math.max(0.15, startL+dFr); cw[idx+1] = Math.max(0.15, startR-dFr); container.style.gridTemplateColumns = cw.map(v => v+'fr').join(' '); repositionHandles(); }
    function onUp() { handle.classList.remove('active'); handle.removeEventListener('pointermove', onMove); handle.removeEventListener('pointerup', onUp); saveLayoutPref(); }
    handle.addEventListener('pointermove', onMove);
    handle.addEventListener('pointerup', onUp);
  });
  handle.addEventListener('dblclick', () => { ensureCustomWeights(); S.customWeights.cols = S.customWeights.cols.map(() => 1); container.style.gridTemplateColumns = S.customWeights.cols.map(v => v+'fr').join(' '); repositionHandles(); saveLayoutPref(); });
}

function initRowResize(handle, idx) {
  handle.addEventListener('pointerdown', (e) => {
    e.preventDefault(); handle.setPointerCapture(e.pointerId); handle.classList.add('active');
    ensureCustomWeights();
    const startY = e.clientY, rw = S.customWeights.rows;
    const totalFr = rw.reduce((s,v) => s+v, 0), frToPx = container.clientHeight / totalFr;
    const startT = rw[idx], startB = rw[idx+1];
    function onMove(ev) { const dy = ev.clientY - startY, dFr = dy/frToPx; rw[idx] = Math.max(0.15, startT+dFr); rw[idx+1] = Math.max(0.15, startB-dFr); container.style.gridTemplateRows = rw.map(v => v+'fr').join(' '); repositionHandles(); }
    function onUp() { handle.classList.remove('active'); handle.removeEventListener('pointermove', onMove); handle.removeEventListener('pointerup', onUp); saveLayoutPref(); }
    handle.addEventListener('pointermove', onMove);
    handle.addEventListener('pointerup', onUp);
  });
  handle.addEventListener('dblclick', () => { ensureCustomWeights(); S.customWeights.rows = S.customWeights.rows.map(() => 1); container.style.gridTemplateRows = S.customWeights.rows.map(v => v+'fr').join(' '); repositionHandles(); saveLayoutPref(); });
}

// ── Persistence ──

function saveLayoutPref() {
  try { localStorage.setItem('tmux-webui-layout', JSON.stringify({ layout: S.currentLayout, weights: S.customWeights })); } catch(e) {}
}
function loadLayoutPref() {
  try {
    const s = localStorage.getItem('tmux-webui-layout');
    if (s) { const o = JSON.parse(s); if (o.layout && LAYOUT_PRESETS[o.layout]) { S.currentLayout = o.layout; layoutSelect.value = S.currentLayout; } if (o.weights) S.customWeights = o.weights; }
  } catch(e) {}
}
function savePaneOrder() {
  if (S.currentSession) { try { localStorage.setItem('tmux-webui-order-'+S.currentSession, JSON.stringify(S.paneOrder)); } catch(e) {} }
}
function loadPaneOrder() {
  try { const s = localStorage.getItem('tmux-webui-order-'+S.currentSession); if (s) S.paneOrder = JSON.parse(s); else S.paneOrder = []; } catch(e) { S.paneOrder = []; }
}

// ========================================================================
// 9. Pane Management
// ========================================================================

function ensurePaneOrder(ids) {
  const idSet = new Set(ids);
  const kept = S.paneOrder.filter(id => idSet.has(id));
  for (const id of ids) { if (!kept.includes(id)) kept.push(id); }
  S.paneOrder = kept;
}

function reorderDOM() {
  const handles = [...container.querySelectorAll('.resize-handle')];
  for (const id of S.paneOrder) { if (S.paneEls[id]) container.appendChild(S.paneEls[id].box); }
  handles.forEach(h => container.appendChild(h));
}

function toggleMaximize(paneId) {
  if (S.maximizedPane === paneId) {
    S.maximizedPane = '';
    container.classList.remove('has-maximized');
    Object.values(S.paneEls).forEach(pe => { pe.box.classList.remove('maximized'); pe.box.querySelector('.pane-header').draggable = true; });
    rebuildResizeHandles();
  } else {
    S.maximizedPane = paneId;
    container.classList.add('has-maximized');
    Object.values(S.paneEls).forEach(pe => { pe.box.classList.remove('maximized'); pe.box.querySelector('.pane-header').draggable = false; });
    if (S.paneEls[paneId]) S.paneEls[paneId].box.classList.add('maximized');
    setFocus(paneId);
    container.querySelectorAll('.resize-handle').forEach(h => h.remove());
  }
}

function buildPaneEl(p) {
  const box = document.createElement('div');
  box.className = 'pane-box';
  box.dataset.paneId = p.id;

  const toolKey = detectTool(p);
  const toolBadge = toolKey ? `<span class="pane-tool">${TOOL_PROFILES[toolKey].name}</span>` : '';

  const hdr = document.createElement('div');
  hdr.className = 'pane-header';
  hdr.innerHTML = `<span class="pane-label">${esc(p.window_name)}:${esc(String(p.pane))}</span>${toolBadge}`
    + `<span class="pane-cmd">${esc(p.command)}</span>`
    + `<button class="pane-maximize" title="Maximize / Restore">&#x26F6;</button>`;
  box.appendChild(hdr);

  hdr.querySelector('.pane-maximize').addEventListener('click', (e) => { e.stopPropagation(); toggleMaximize(p.id); });
  hdr.addEventListener('dblclick', (e) => { e.stopPropagation(); toggleMaximize(p.id); });

  // Drag to reorder
  hdr.draggable = true;
  hdr.addEventListener('dragstart', (e) => { e.dataTransfer.setData('text/plain', p.id); e.dataTransfer.effectAllowed = 'move'; requestAnimationFrame(() => box.classList.add('dragging')); });
  hdr.addEventListener('dragend', () => { box.classList.remove('dragging'); container.querySelectorAll('.pane-box.drag-over').forEach(el => el.classList.remove('drag-over')); });
  box.addEventListener('dragover', (e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; if (!box.classList.contains('dragging')) box.classList.add('drag-over'); });
  box.addEventListener('dragleave', () => box.classList.remove('drag-over'));
  box.addEventListener('drop', (e) => {
    e.preventDefault(); box.classList.remove('drag-over');
    const srcId = e.dataTransfer.getData('text/plain');
    if (srcId === p.id) return;
    const si = S.paneOrder.indexOf(srcId), ti = S.paneOrder.indexOf(p.id);
    if (si === -1 || ti === -1) return;
    S.paneOrder.splice(si, 1); S.paneOrder.splice(ti, 0, srcId);
    reorderDOM(); applyLayout(); savePaneOrder();
  });

  const term = document.createElement('div');
  term.className = 'pane-terminal';
  box.appendChild(term);

  let scrolledByUser = false;
  term.addEventListener('scroll', () => { scrolledByUser = (term.scrollHeight - term.scrollTop - term.clientHeight) > 60; });

  box.addEventListener('click', () => setFocus(p.id));

  S.paneEls[p.id] = { box, terminal: term, scrolledByUser: () => scrolledByUser, resetScroll: () => { scrolledByUser = false; } };
  S.paneInfo[p.id] = p;
  return box;
}

function setFocus(paneId) {
  S.focusedPane = paneId;
  Object.values(S.paneEls).forEach(pe => pe.box.classList.remove('focused'));
  if (S.paneEls[paneId]) {
    S.paneEls[paneId].box.classList.add('focused');
    const info = S.paneInfo[paneId];
    const toolKey = detectTool(info);
    const toolName = toolKey ? ` [${TOOL_PROFILES[toolKey].name}]` : '';
    focusLabel.textContent = info ? `${info.window_name}:${info.pane}${toolName}` : paneId;
    renderToolActions(toolKey);
  }
  updateMobilePaneTabs();
}

function renderPanes(panes) {
  const oldFocus = S.focusedPane;
  const existingIds = new Set(Object.keys(S.paneEls));
  const newIds = new Set(panes.map(p => p.id));

  for (const gone of existingIds) {
    if (!newIds.has(gone)) { S.paneEls[gone].box.remove(); delete S.paneEls[gone]; delete S.paneInfo[gone]; }
  }
  for (const p of panes) {
    if (!S.paneEls[p.id]) {
      container.appendChild(buildPaneEl(p));
    } else {
      S.paneInfo[p.id] = p;
      const hdr = S.paneEls[p.id].box.querySelector('.pane-header');
      const lbl = hdr.querySelector('.pane-label');
      const cmd = hdr.querySelector('.pane-cmd');
      if (lbl) lbl.textContent = `${p.window_name}:${p.pane}`;
      if (cmd) cmd.textContent = p.command;
    }
  }

  ensurePaneOrder(panes.map(p => p.id));
  reorderDOM();
  applyLayout();

  if (newIds.has(oldFocus)) setFocus(oldFocus);
  else if (panes.length > 0) setFocus(panes[0].id);

  if (S.maximizedPane && newIds.has(S.maximizedPane)) {
    container.classList.add('has-maximized');
    Object.values(S.paneEls).forEach(pe => pe.box.classList.remove('maximized'));
    S.paneEls[S.maximizedPane].box.classList.add('maximized');
  } else if (S.maximizedPane && !newIds.has(S.maximizedPane)) {
    S.maximizedPane = '';
    container.classList.remove('has-maximized');
  }
}

// ========================================================================
// 10. Mobile Pane Tab Bar
// ========================================================================

function updateMobilePaneTabs() {
  if (!mobilePaneTabs) return;
  const isMobile = window.matchMedia('(max-width:600px)').matches;
  const panes = S.paneOrder.filter(id => S.paneEls[id]);

  if (!isMobile || panes.length <= 1) {
    mobilePaneTabs.classList.remove('visible');
    // Show all panes on desktop
    panes.forEach(id => S.paneEls[id].box.classList.remove('mobile-active'));
    return;
  }

  mobilePaneTabs.classList.add('visible');
  mobilePaneTabs.innerHTML = '';

  panes.forEach(id => {
    const info = S.paneInfo[id];
    const tab = document.createElement('button');
    tab.className = 'mobile-pane-tab' + (id === S.focusedPane ? ' active' : '');
    const cmdShort = (info?.command || '').slice(0, 8);
    tab.innerHTML = `${esc(info?.window_name || '')}:${esc(String(info?.pane || ''))}<span class="tab-cmd">${esc(cmdShort)}</span>`;
    tab.addEventListener('click', () => {
      setFocus(id);
      // Show only this pane
      panes.forEach(pid => S.paneEls[pid].box.classList.toggle('mobile-active', pid === id));
      updateMobilePaneTabs();
    });
    mobilePaneTabs.appendChild(tab);

    // Show/hide pane boxes
    S.paneEls[id].box.classList.toggle('mobile-active', id === S.focusedPane);
  });
}

window.switchMobilePane = function(direction) {
  const panes = S.paneOrder.filter(id => S.paneEls[id]);
  if (panes.length <= 1) return;
  const idx = panes.indexOf(S.focusedPane);
  const next = (idx + direction + panes.length) % panes.length;
  setFocus(panes[next]);
  panes.forEach(pid => S.paneEls[pid].box.classList.toggle('mobile-active', pid === panes[next]));
  updateMobilePaneTabs();
};

// ========================================================================
// 11. Window Tabs
// ========================================================================

function renderWindowTabs(windows, activeWin) {
  S.activeWindowIdx = activeWin;
  winTabsEl.innerHTML = '';
  if (!windows || windows.length === 0) { winTabsEl.style.display = 'none'; return; }
  winTabsEl.style.display = '';
  windows.forEach(w => {
    const tab = document.createElement('button');
    tab.className = 'win-tab' + (w.index === activeWin ? ' active' : '');
    tab.textContent = `${w.index}:${w.name} (${w.panes})`;
    tab.title = `Window ${w.index}: ${w.name}`;
    tab.addEventListener('click', () => {
      if (w.index === S.activeWindowIdx) return;
      window.tmuxWs?.send({ type:'switch_window', window:w.index });
    });
    if (windows.length > 1) {
      const x = document.createElement('span');
      x.className = 'win-tab-x';
      x.textContent = '\u00d7';
      x.addEventListener('click', (e) => {
        e.stopPropagation();
        if (!confirm(`Close window ${w.index}:${w.name}?`)) return;
        window.tmuxWs?.send({ type:'close_window', window:w.index });
      });
      tab.appendChild(x);
    }
    winTabsEl.appendChild(tab);
  });
  const addBtn = document.createElement('button');
  addBtn.className = 'win-tab win-tab-add';
  addBtn.textContent = '+';
  addBtn.addEventListener('click', () => window.tmuxWs?.send({ type:'new_window' }));
  winTabsEl.appendChild(addBtn);
}

// ========================================================================
// 12. WebSocket with Exponential Backoff Reconnection
// ========================================================================

window.tmuxWs = (function() {
  let ws = null;
  let reconnectDelay = 1000;
  const MAX_DELAY = 30000;

  function isConnected() { return ws && ws.readyState === WebSocket.OPEN; }

  function send(data) {
    if (isConnected()) ws.send(JSON.stringify(data));
  }

  function setStatus(state, text) {
    statusEl.className = state;
    if (state === 'connected') {
      statusEl.innerHTML = `<span class="dot"></span> ${text}`;
      connectBtn.textContent = 'disconnect';
      connectBtn.classList.remove('btn-accent');
      inputEl.disabled = false;
      sendBtn.disabled = false;
      inputEl.focus();
      reconnectDelay = 1000; // Reset on successful connection
    } else if (state === 'reconnecting') {
      statusEl.innerHTML = `<span class="dot"></span> reconnecting (${Math.round(reconnectDelay/1000)}s)...`;
    } else {
      statusEl.innerHTML = '<span class="dot"></span> disconnected';
      connectBtn.textContent = 'connect';
      connectBtn.classList.add('btn-accent');
      inputEl.disabled = true;
      sendBtn.disabled = true;
      focusLabel.textContent = 'no pane';
      winTabsEl.innerHTML = '';
      winTabsEl.style.display = 'none';
      document.getElementById('tmux-status').innerHTML = '';
      document.getElementById('tmux-status').style.display = 'none';
      if (mobilePaneTabs) mobilePaneTabs.classList.remove('visible');
    }
  }

  function connect(session) {
    if (ws) { ws.close(); ws = null; }
    S.currentSession = session;
    S.focusedPane = '';
    S.paneEls = {};
    S.paneInfo = {};
    S.paneOrder = [];
    S.currentTool = null;
    container.innerHTML = '';

    loadPaneOrder();

    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const basePath = location.pathname.replace(/\/+$/, '') || '';
    ws = new WebSocket(`${proto}://${location.host}${basePath}/ws?session=${encodeURIComponent(session)}`);

    ws.onopen = () => setStatus('connected', session);

    ws.onmessage = (e) => {
      const data = JSON.parse(e.data);
      if (data.type === 'panes') {
        renderPanes(data.panes);
      } else if (data.type === 'output') {
        for (const [paneId, content] of Object.entries(data.panes)) {
          const pe = S.paneEls[paneId];
          if (!pe) continue;
          pe.terminal.innerHTML = ansiToHtml(content);
          if (!pe.scrolledByUser()) {
            const t = pe.terminal;
            requestAnimationFrame(() => { requestAnimationFrame(() => { t.scrollTop = t.scrollHeight; }); });
          }
        }
      } else if (data.type === 'windows') {
        renderWindowTabs(data.windows, data.active);
      } else if (data.type === 'metrics') {
        window.renderMetrics?.(data.metrics);
      } else if (data.type === 'input_error') {
        window.flashInputError(data.message);
      } else if (data.type === 'autocomplete') {
        window.handleAutocomplete?.(data.results);
      } else if (data.type === 'error') {
        container.innerHTML = `<div class="welcome" style="color:var(--red)">${esc(data.message)}</div>`;
      }
    };

    ws.onclose = () => {
      if (S.currentSession === session) {
        setStatus('reconnecting', '');
        const savedMaximized = S.maximizedPane;
        setTimeout(() => {
          if (S.currentSession === session && (!ws || ws.readyState === WebSocket.CLOSED)) {
            reconnectDelay = Math.min(reconnectDelay * 2, MAX_DELAY);
            connect(session);
            if (savedMaximized) {
              const check = setInterval(() => {
                if (S.paneEls[savedMaximized]) { clearInterval(check); toggleMaximize(savedMaximized); }
              }, 300);
              setTimeout(() => clearInterval(check), 5000);
            }
          }
        }, reconnectDelay);
      } else {
        setStatus('', '');
      }
    };

    ws.onerror = () => {};
  }

  function disconnect() {
    S.currentSession = '';
    S.maximizedPane = '';
    S.currentTool = null;
    S.skillPaletteOpen = false;
    if (skillPalette) skillPalette.style.display = 'none';
    if (ws) { ws.close(); ws = null; }
    setStatus('', '');
    container.classList.remove('has-maximized');
    container.innerHTML = '<div class="welcome">select a tmux session to connect</div>';
    toolActionsEl.innerHTML = '';
    S.paneEls = {};
    S.paneInfo = {};
    S.paneOrder = [];
  }

  return { connect, disconnect, send, isConnected };
})();

// ========================================================================
// 13. Sessions
// ========================================================================

async function loadSessions() {
  try {
    const basePath = location.pathname.replace(/\/+$/, '') || '';
    const res = await fetch(basePath + '/api/sessions');
    const list = await res.json();
    sessionsEl.innerHTML = '<option value="">-- select session --</option>';
    list.forEach(s => {
      const opt = document.createElement('option');
      opt.value = s.name;
      opt.textContent = `${s.name}  [${s.windows}w]${s.attached ? ' (attached)' : ''}`;
      sessionsEl.appendChild(opt);
    });
  } catch(e) {
    sessionsEl.innerHTML = '<option value="">tmux not available</option>';
  }
}

sessionsEl.addEventListener('change', () => { connectBtn.disabled = !sessionsEl.value; });
refreshBtn.addEventListener('click', loadSessions);
connectBtn.addEventListener('click', () => {
  if (S.currentSession) window.tmuxWs.disconnect();
  else { const s = sessionsEl.value; if (s) window.tmuxWs.connect(s); }
});

// ========================================================================
// 14. Quick Actions
// ========================================================================

document.querySelectorAll('.qbtn').forEach(btn => {
  btn.addEventListener('click', () => {
    const key = btn.dataset.key;
    if (!window.tmuxWs.isConnected() || !S.focusedPane) return;
    window.tmuxWs.send({ type:'key', pane:S.focusedPane, key });
    if (S.paneEls[S.focusedPane]) S.paneEls[S.focusedPane].resetScroll();
  });
});

// ========================================================================
// 15. Keyboard Shortcuts
// ========================================================================

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && S.maximizedPane && document.activeElement !== inputEl) toggleMaximize(S.maximizedPane);
  if ((e.ctrlKey || e.metaKey) && e.key === 'k' && S.currentTool === 'claude' && skillPalette) {
    e.preventDefault();
    S.skillPaletteOpen = !S.skillPaletteOpen;
    skillPalette.style.display = S.skillPaletteOpen ? '' : 'none';
    if (S.skillPaletteOpen) { renderSkillPalette(); if (skillSearchEl) skillSearchEl.focus(); }
  }
});

// ========================================================================
// 16. Layout Controls
// ========================================================================

layoutSelect.addEventListener('change', () => { S.currentLayout = layoutSelect.value; S.customWeights = null; applyLayout(); saveLayoutPref(); });
resetLayoutBtn.addEventListener('click', () => { S.customWeights = null; applyLayout(); saveLayoutPref(); });
window.addEventListener('resize', () => { if (!S.maximizedPane && S.currentLayout !== 'auto') rebuildResizeHandles(); updateMobilePaneTabs(); });

// ========================================================================
// 17. Terminal Fit (sync WebUI size → tmux pane size)
// ========================================================================

(function() {
  const probe = document.createElement('span');
  probe.style.cssText = 'position:absolute;visibility:hidden;white-space:pre;font-family:var(--font-mono);font-size:var(--font-size);line-height:1.5;';
  probe.textContent = 'X';
  document.body.appendChild(probe);
  let charW = 0, lineH = 0;
  function measureChar() {
    const r = probe.getBoundingClientRect();
    charW = r.width; lineH = r.height;
  }
  function fitPane(paneId) {
    const pe = S.paneEls[paneId];
    if (!pe || !charW || !lineH) return;
    const cols = Math.floor(pe.terminal.clientWidth / charW);
    const rows = Math.floor(pe.terminal.clientHeight / lineH);
    if (cols > 0 && rows > 0 && window.tmuxWs.isConnected()) {
      window.tmuxWs.send({ type: 'fit', pane: paneId, cols, rows });
    }
  }
  function fitAllPanes() {
    measureChar();
    const panes = S.paneOrder.length ? S.paneOrder.filter(id => S.paneEls[id]) : Object.keys(S.paneEls);
    for (const id of panes) {
      const pe = S.paneEls[id];
      if (pe && pe.box.style.display !== 'none' && !pe.box.classList.contains('dragging')) fitPane(id);
    }
  }
  let fitTimer = null;
  function debouncedFit() { clearTimeout(fitTimer); fitTimer = setTimeout(fitAllPanes, 300); }
  window._fitAllPanes = debouncedFit;
  window.addEventListener('resize', debouncedFit);
})();

// ========================================================================
// 18. Init
// ========================================================================

loadLayoutPref();
loadSessions();
