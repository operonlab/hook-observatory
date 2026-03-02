/**
 * autocomplete.js — Frontend autocomplete UI
 * Integrates with server-side path/command/skill completion via WebSocket
 */

(function() {
  const acList = document.getElementById('ac-list');
  const inputEl = document.getElementById('input');
  let acIdx = -1;
  let acItems = [];
  let debounceTimer = null;

  function acOpen(items) {
    acItems = items;
    acList.innerHTML = '';
    items.forEach((item, i) => {
      const div = document.createElement('div');
      div.className = 'ac-item' + (i === acIdx ? ' active' : '');

      const text = document.createElement('span');
      text.textContent = item.display;
      div.appendChild(text);

      if (item.category) {
        const cat = document.createElement('span');
        cat.className = 'ac-cat';
        cat.textContent = item.category;
        div.appendChild(cat);
      }

      const typeBadge = document.createElement('span');
      typeBadge.className = 'ac-type ' + (item.type || '');
      typeBadge.textContent = item.type || '';
      div.appendChild(typeBadge);

      div.addEventListener('mousedown', (e) => {
        e.preventDefault();
        acSelect(item);
      });
      acList.appendChild(div);
    });
    acList.classList.toggle('open', items.length > 0);
  }

  function acClose() {
    acList.classList.remove('open');
    acIdx = -1;
    acItems = [];
  }

  function acSelect(item) {
    if (item.type === 'skill') {
      // Skills that end with space → fill input; otherwise send directly
      if (item.text.endsWith(' ')) {
        inputEl.value = item.text;
        inputEl.focus();
      } else {
        inputEl.value = '';
        window.sendSkillOrAction?.(item.text);
      }
    } else if (item.type === 'history') {
      inputEl.value = item.text;
      inputEl.focus();
    } else {
      // Path: replace current token
      inputEl.value = item.text;
      inputEl.focus();
    }
    acClose();
  }

  function acFilter() {
    const val = inputEl.value;
    if (!val || val.includes('\n')) { acClose(); return; }

    // Debounce for path/command completion (needs server round-trip)
    clearTimeout(debounceTimer);

    if (val.startsWith('/')) {
      // Skill completion: request via WebSocket
      debounceTimer = setTimeout(() => {
        if (window.tmuxWs && window.tmuxWs.isConnected()) {
          window.tmuxWs.send({ type: 'autocomplete', query: val });
        }
      }, 100);
    } else if (val.startsWith('~') || val.startsWith('./') || val.startsWith('/')) {
      // Path completion
      debounceTimer = setTimeout(() => {
        if (window.tmuxWs && window.tmuxWs.isConnected()) {
          window.tmuxWs.send({ type: 'autocomplete', query: val });
        }
      }, 150);
    } else if (val.length >= 2) {
      // Command history
      debounceTimer = setTimeout(() => {
        if (window.tmuxWs && window.tmuxWs.isConnected()) {
          window.tmuxWs.send({ type: 'autocomplete', query: val });
        }
      }, 200);
    } else {
      acClose();
    }
  }

  // Handle autocomplete results from server
  window.handleAutocomplete = function(results) {
    if (!results || results.length === 0) {
      acClose();
      return;
    }
    acIdx = -1;
    acOpen(results);
  };

  // Keyboard navigation in autocomplete
  inputEl.addEventListener('keydown', (e) => {
    if (acList.classList.contains('open')) {
      const items = acList.querySelectorAll('.ac-item');
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        acIdx = Math.min(acIdx + 1, items.length - 1);
        items.forEach((el, i) => el.classList.toggle('active', i === acIdx));
        items[acIdx]?.scrollIntoView({ block: 'nearest' });
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        acIdx = Math.max(acIdx - 1, 0);
        items.forEach((el, i) => el.classList.toggle('active', i === acIdx));
        items[acIdx]?.scrollIntoView({ block: 'nearest' });
        return;
      }
      if (e.key === 'Tab' || (e.key === 'Enter' && acIdx >= 0)) {
        e.preventDefault();
        if (acItems[acIdx]) acSelect(acItems[acIdx]);
        return;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        acClose();
        return;
      }
    }

    // Normal Enter → send input
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      acClose();
      window.sendInput?.();
    }
  });

  inputEl.addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 120) + 'px';
    acFilter();
  });

  inputEl.addEventListener('blur', () => setTimeout(acClose, 150));

  // Expose
  window.acClose = acClose;
})();
