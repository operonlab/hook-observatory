/**
 * gestures.js — Touch gesture handling (Blink Shell / iSH inspired)
 * - Swipe left/right: switch tmux pane
 * - Pinch zoom: adjust font size
 * - Long press: trigger text selection
 * - Bottom swipe up: toggle virtual keyboard
 */

(function() {
  const container = document.getElementById('pane-container');
  const indicator = document.getElementById('gesture-indicator');
  const isMobile = () => window.matchMedia('(max-width:600px)').matches;

  // ── Font size persistence ──
  let fontSize = parseFloat(localStorage.getItem('tmux-webui-font-size') || '12');
  document.documentElement.style.setProperty('--font-size', fontSize + 'px');

  // ── Gesture state ──
  let touchStartX = 0, touchStartY = 0, touchStartTime = 0;
  let isPinching = false, initialPinchDist = 0, initialFontSize = 12;
  let longPressTimer = null;
  const SWIPE_THRESHOLD = 80;
  const LONG_PRESS_MS = 500;

  function showIndicator(text) {
    if (!indicator) return;
    indicator.textContent = text;
    indicator.classList.add('show');
    setTimeout(() => indicator.classList.remove('show'), 400);
  }

  // ── Swipe: switch pane (mobile) or send arrow keys ──

  container.addEventListener('touchstart', (e) => {
    if (e.touches.length === 2) {
      // Start pinch
      isPinching = true;
      initialPinchDist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY
      );
      initialFontSize = fontSize;
      return;
    }
    if (e.touches.length !== 1) return;

    isPinching = false;
    touchStartX = e.touches[0].clientX;
    touchStartY = e.touches[0].clientY;
    touchStartTime = Date.now();

    // Long press detection
    longPressTimer = setTimeout(() => {
      // Trigger native text selection
      const sel = window.getSelection();
      if (sel) sel.removeAllRanges();
      showIndicator('Select');
    }, LONG_PRESS_MS);
  }, { passive: true });

  container.addEventListener('touchmove', (e) => {
    // Cancel long press on move
    if (longPressTimer) {
      clearTimeout(longPressTimer);
      longPressTimer = null;
    }

    // Handle pinch zoom
    if (isPinching && e.touches.length === 2) {
      const dist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY
      );
      const scale = dist / initialPinchDist;
      fontSize = Math.max(8, Math.min(24, Math.round(initialFontSize * scale)));
      document.documentElement.style.setProperty('--font-size', fontSize + 'px');
      return;
    }
  }, { passive: true });

  container.addEventListener('touchend', (e) => {
    if (longPressTimer) {
      clearTimeout(longPressTimer);
      longPressTimer = null;
    }

    // Save font size after pinch
    if (isPinching) {
      isPinching = false;
      localStorage.setItem('tmux-webui-font-size', String(fontSize));
      return;
    }

    if (e.changedTouches.length !== 1) return;
    const dx = e.changedTouches[0].clientX - touchStartX;
    const dy = e.changedTouches[0].clientY - touchStartY;
    const elapsed = Date.now() - touchStartTime;

    // Only process quick swipes (<300ms)
    if (elapsed > 300) return;
    if (Math.abs(dy) > Math.abs(dx)) return; // vertical, ignore
    if (Math.abs(dx) < SWIPE_THRESHOLD) return;

    if (isMobile() && window.switchMobilePane) {
      // Mobile: switch pane tabs
      if (dx > 0) {
        window.switchMobilePane(-1);
        showIndicator('\u25C0');
      } else {
        window.switchMobilePane(1);
        showIndicator('\u25B6');
      }
    } else if (window.tmuxWs && window.tmuxWs.isConnected()) {
      // Desktop: send pane direction to tmux
      const dir = dx > 0 ? 'right' : 'left';
      window.tmuxWs.send({
        type: 'select_pane_direction',
        pane: window.tmuxState.focusedPane,
        direction: dir,
      });
      showIndicator(dx > 0 ? '\u25B6' : '\u25C0');
    }
  }, { passive: true });

  // ── Bottom swipe up: toggle virtual keyboard ──

  let bottomSwipeY = 0;
  const footer = document.querySelector('footer');

  if (footer) {
    footer.addEventListener('touchstart', (e) => {
      if (e.touches.length !== 1) return;
      bottomSwipeY = e.touches[0].clientY;
    }, { passive: true });

    footer.addEventListener('touchend', (e) => {
      if (e.changedTouches.length !== 1) return;
      const dy = bottomSwipeY - e.changedTouches[0].clientY;
      if (dy > 60) {
        // Swipe up → expand footer & show extra keys
        footer.classList.remove('mobile-collapsed');
        window.applyEkVisibility?.(true);
      } else if (dy < -60) {
        // Swipe down → collapse
        footer.classList.add('mobile-collapsed');
      }
    }, { passive: true });
  }

  // ── Virtual keyboard height tracking ──

  if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', () => {
      const kbH = Math.max(0, window.innerHeight - window.visualViewport.height);
      document.documentElement.style.setProperty('--kb-height', kbH + 'px');
    });
  }
})();
