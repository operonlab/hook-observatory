/**
 * keys.js — Virtual keys + Ctrl combo mode (Blink Shell style)
 * V2: Added /, ., :, ; keys + improved Ctrl combo UX
 */

(function() {
  const extraKeysEl = document.getElementById('extra-keys');
  const ekToggleBtn = document.getElementById('ek-toggle');
  const arrowPad = document.getElementById('arrow-pad');
  const activeModifiers = new Set();
  const modLockTimers = {};

  // ── Modifier keys (Ctrl/Alt/Cmd) ──

  document.querySelectorAll('.ek.mod').forEach(btn => {
    let lastTap = 0;
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const mod = btn.dataset.mod;
      const now = Date.now();
      if (btn.classList.contains('locked')) {
        btn.classList.remove('locked', 'active');
        activeModifiers.delete(mod);
      } else if (now - lastTap < 350 && btn.classList.contains('active')) {
        // Double-tap → lock
        btn.classList.add('locked');
        clearTimeout(modLockTimers[mod]);
      } else {
        if (activeModifiers.has(mod)) {
          activeModifiers.delete(mod);
          btn.classList.remove('active');
        } else {
          activeModifiers.add(mod);
          btn.classList.add('active');
        }
      }
      lastTap = now;
    });
  });

  function clearModifiers() {
    activeModifiers.clear();
    document.querySelectorAll('.ek.mod').forEach(b => {
      if (!b.classList.contains('locked')) b.classList.remove('active');
    });
  }

  function sendEk(key) {
    if (!window.tmuxWs || !window.tmuxWs.isConnected() || !window.tmuxState.focusedPane) {
      window.flashInputError?.('Not connected');
      return;
    }
    const mods = [...activeModifiers];
    window.tmuxWs.send({
      type: 'key',
      pane: window.tmuxState.focusedPane,
      key,
      modifiers: mods,
    });
    const pe = window.tmuxState.paneEls[window.tmuxState.focusedPane];
    if (pe) pe.resetScroll();
    clearModifiers();
  }

  // Expose for gestures.js
  window.sendEk = sendEk;

  // ── Common extra keys + arrow buttons ──

  document.querySelectorAll('.ek[data-ek]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      sendEk(btn.dataset.ek);
    });
  });

  // ── Ctrl+C / Ctrl+D / Ctrl+Z / Ctrl+L standalone buttons ──

  document.querySelectorAll('.ek[data-ctrl]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      if (!window.tmuxWs || !window.tmuxWs.isConnected() || !window.tmuxState.focusedPane) return;
      window.tmuxWs.send({
        type: 'key',
        pane: window.tmuxState.focusedPane,
        key: btn.dataset.ctrl,
        modifiers: ['C'],
      });
    });
  });

  // ── Arrow Touchpad ──

  if (arrowPad) {
    const THRESHOLD = 18;
    let tracking = false, lastX = 0, lastY = 0, dirClass = '';

    function clearDir() {
      if (dirClass) { arrowPad.classList.remove(dirClass); dirClass = ''; }
    }

    function handleMove(cx, cy) {
      const dx = cx - lastX, dy = cy - lastY;
      const ax = Math.abs(dx), ay = Math.abs(dy);
      if (ax < THRESHOLD && ay < THRESHOLD) return;
      let key, cls;
      if (ax > ay) {
        key = dx > 0 ? 'Right' : 'Left';
        cls = dx > 0 ? 'dir-right' : 'dir-left';
      } else {
        key = dy > 0 ? 'Down' : 'Up';
        cls = dy > 0 ? 'dir-down' : 'dir-up';
      }
      lastX = cx; lastY = cy;
      clearDir();
      dirClass = cls;
      arrowPad.classList.add(cls);
      sendEk(key);
    }

    arrowPad.addEventListener('touchstart', (e) => {
      e.preventDefault();
      const t = e.touches[0];
      tracking = true; lastX = t.clientX; lastY = t.clientY;
    }, { passive: false });

    arrowPad.addEventListener('touchmove', (e) => {
      e.preventDefault();
      if (!tracking) return;
      handleMove(e.touches[0].clientX, e.touches[0].clientY);
    }, { passive: false });

    arrowPad.addEventListener('touchend', () => { tracking = false; clearDir(); });

    // Mouse fallback
    arrowPad.addEventListener('mousedown', (e) => {
      e.preventDefault();
      tracking = true; lastX = e.clientX; lastY = e.clientY;
      const onMove = (ev) => handleMove(ev.clientX, ev.clientY);
      const onUp = () => {
        tracking = false; clearDir();
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
  }

  // ── Extra Keys Toggle ──

  function isTouch() { return matchMedia('(pointer:coarse)').matches; }

  function loadEkPref() {
    const stored = localStorage.getItem('tmux-webui-show-extra-keys');
    if (stored !== null) return stored === '1';
    return isTouch();
  }

  function applyEkVisibility(show) {
    extraKeysEl.classList.toggle('visible', show);
    ekToggleBtn.classList.toggle('active', show);
  }

  applyEkVisibility(loadEkPref());

  ekToggleBtn.addEventListener('click', () => {
    const show = !extraKeysEl.classList.contains('visible');
    applyEkVisibility(show);
    localStorage.setItem('tmux-webui-show-extra-keys', show ? '1' : '0');
  });

  // Mobile toolbar toggle
  const footerEl = document.querySelector('footer');
  const toolbarToggleBtn = document.getElementById('toolbar-toggle');
  if (window.matchMedia('(max-width:600px)').matches) {
    footerEl.classList.add('mobile-collapsed');
  }
  toolbarToggleBtn?.addEventListener('click', () => {
    const collapsed = footerEl.classList.toggle('mobile-collapsed');
    toolbarToggleBtn.classList.toggle('active', !collapsed);
  });

  // Expose
  window.applyEkVisibility = applyEkVisibility;
})();
