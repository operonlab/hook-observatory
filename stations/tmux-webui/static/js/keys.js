/**
 * keys.js — Virtual keys + Ctrl combo mode (Blink Shell style)
 * V2: Added /, ., :, ; keys + improved Ctrl combo UX
 */

(function() {
  const extraKeysEl = document.getElementById('extra-keys');
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

  // ── Tmux Prefix Mode (Ctrl-b then next key within timeout) ──

  let prefixActive = false;
  let prefixTimer = null;
  const PREFIX_TIMEOUT = 2000; // 2 seconds to press next key

  function enterPrefixMode() {
    prefixActive = true;
    clearTimeout(prefixTimer);
    // Visual indicator
    const statusEl = document.getElementById('status');
    if (statusEl) statusEl.dataset.prefix = 'active';
    document.body.classList.add('tmux-prefix-active');
    // Send Ctrl-b immediately
    if (window.tmuxWs?.isConnected() && window.tmuxState.focusedPane) {
      window.tmuxWs.send({
        type: 'key',
        pane: window.tmuxState.focusedPane,
        key: 'b',
        modifiers: ['C'],
      });
    }
    // Auto-expire after timeout
    prefixTimer = setTimeout(() => {
      prefixActive = false;
      document.body.classList.remove('tmux-prefix-active');
      if (statusEl) delete statusEl.dataset.prefix;
    }, PREFIX_TIMEOUT);
  }

  function sendEk(key) {
    if (!window.tmuxWs || !window.tmuxWs.isConnected() || !window.tmuxState.focusedPane) {
      window.flashInputError?.('Not connected');
      return;
    }

    // If prefix mode is active, send key directly (tmux already received Ctrl-b)
    if (prefixActive) {
      prefixActive = false;
      clearTimeout(prefixTimer);
      document.body.classList.remove('tmux-prefix-active');
      const statusEl = document.getElementById('status');
      if (statusEl) delete statusEl.dataset.prefix;
      window.tmuxWs.send({
        type: 'key',
        pane: window.tmuxState.focusedPane,
        key,
        modifiers: [],
      });
      const pe = window.tmuxState.paneEls[window.tmuxState.focusedPane];
      if (pe) pe.resetScroll();
      clearModifiers();
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

  // Expose prefix mode for external use
  window.enterTmuxPrefix = enterPrefixMode;

  // Expose for gestures.js
  window.sendEk = sendEk;

  // ── Prefix button ──

  const prefixBtn = document.getElementById('prefix-btn');
  if (prefixBtn) {
    prefixBtn.addEventListener('click', (e) => {
      e.preventDefault();
      enterPrefixMode();
    });
  }

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

  // ── Arrow Touchpad (shared logic for all .arrow-pad elements) ──

  function initArrowPad(pad) {
    if (!pad) return;
    const THRESHOLD = 18;
    const COOLDOWN = 150;
    const REPEAT_DELAY = 400; // ms before repeat starts
    const REPEAT_RATE = 120;  // ms between repeats
    let tracking = false, lastX = 0, lastY = 0, dirClass = '', lastSendTime = 0;
    let currentKey = null, repeatTimer = null;

    function clearDir() {
      if (dirClass) { pad.classList.remove(dirClass); dirClass = ''; }
    }

    function stopRepeat() {
      clearInterval(repeatTimer);
      repeatTimer = null;
      currentKey = null;
    }

    function startRepeat(key) {
      stopRepeat();
      currentKey = key;
      repeatTimer = setTimeout(() => {
        repeatTimer = setInterval(() => {
          if (currentKey) sendEk(currentKey);
        }, REPEAT_RATE);
      }, REPEAT_DELAY);
    }

    function handleMove(cx, cy) {
      const dx = cx - lastX, dy = cy - lastY;
      const ax = Math.abs(dx), ay = Math.abs(dy);
      if (ax < THRESHOLD && ay < THRESHOLD) return;
      const now = Date.now();
      if (now - lastSendTime < COOLDOWN) return;
      let key, cls;
      if (ax > ay) {
        key = dx > 0 ? 'Right' : 'Left';
        cls = dx > 0 ? 'dir-right' : 'dir-left';
      } else {
        key = dy > 0 ? 'Down' : 'Up';
        cls = dy > 0 ? 'dir-down' : 'dir-up';
      }
      lastX = cx; lastY = cy;
      lastSendTime = now;
      clearDir();
      dirClass = cls;
      pad.classList.add(cls);
      sendEk(key);
      startRepeat(key);
    }

    function stop() { tracking = false; clearDir(); stopRepeat(); }

    pad.addEventListener('touchstart', (e) => {
      e.preventDefault();
      const t = e.touches[0];
      tracking = true; lastX = t.clientX; lastY = t.clientY;
    }, { passive: false });

    pad.addEventListener('touchmove', (e) => {
      e.preventDefault();
      if (!tracking) return;
      handleMove(e.touches[0].clientX, e.touches[0].clientY);
    }, { passive: false });

    pad.addEventListener('touchend', stop);
    pad.addEventListener('touchcancel', stop);

    // Mouse fallback
    pad.addEventListener('mousedown', (e) => {
      e.preventDefault();
      tracking = true; lastX = e.clientX; lastY = e.clientY;
      const onMove = (ev) => handleMove(ev.clientX, ev.clientY);
      const onUp = () => {
        stop();
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
  }

  // Init both arrow pads (extra-keys + quick-actions)
  initArrowPad(arrowPad);
  initArrowPad(document.getElementById('quick-arrow-pad'));

  // ── Extra Keys Visibility ──

  function isTouch() { return matchMedia('(pointer:coarse)').matches; }
  function isPWA() { return matchMedia('(display-mode: standalone)').matches; }

  // Auto-show on touch devices and PWA (tablet+); phone PWA relies on quick-actions
  function loadEkPref() {
    const isPhone = window.matchMedia('(max-width:600px)').matches;
    if (isPWA() && !isPhone) return true;
    const stored = localStorage.getItem('tmux-webui-show-extra-keys');
    if (stored !== null) return stored === '1';
    return isTouch() && !isPhone;
  }

  extraKeysEl.classList.toggle('visible', loadEkPref());

  // Mobile: start collapsed (compact quick-actions, hide extra keys)
  if (window.matchMedia('(max-width:600px)').matches) {
    const footerEl = document.querySelector('footer');
    if (footerEl) footerEl.classList.add('mobile-collapsed');
  }

  // ── Extra Keys Toggle Button ──
  const ekToggle = document.getElementById('ek-toggle');
  if (ekToggle) {
    ekToggle.addEventListener('click', (e) => {
      e.preventDefault();
      const show = !extraKeysEl.classList.contains('visible');
      extraKeysEl.classList.toggle('visible', show);
      localStorage.setItem('tmux-webui-show-extra-keys', show ? '1' : '0');
      // Remove mobile-collapsed when showing extra keys
      const footerEl = document.querySelector('footer');
      if (footerEl && show) footerEl.classList.remove('mobile-collapsed');
      else if (footerEl && !show && window.matchMedia('(max-width:600px)').matches) footerEl.classList.add('mobile-collapsed');
      if (window._fitAllPanes) window._fitAllPanes();
    });
  }
})();
