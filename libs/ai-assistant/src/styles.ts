/**
 * Shadow DOM styles for the AI assistant widget.
 * Adapts to host page theme via CSS custom properties.
 */
export const STYLES = /* css */ `
  :host {
    --ai-bg: var(--ai-assistant-bg, rgba(15, 15, 22, 0.98));
    --ai-surface: var(--ai-assistant-surface, rgba(255, 255, 255, 0.04));
    --ai-border: var(--ai-assistant-border, rgba(255, 255, 255, 0.08));
    --ai-text: var(--ai-assistant-text, rgba(255, 255, 255, 0.8));
    --ai-text-dim: var(--ai-assistant-text-dim, rgba(255, 255, 255, 0.45));
    --ai-accent: var(--ai-assistant-accent, #b4befe);
    --ai-accent-bg: var(--ai-assistant-accent-bg, rgba(180, 190, 254, 0.12));
    --ai-user-bubble: var(--ai-assistant-user-bubble, rgba(180, 190, 254, 0.12));
    --ai-bot-bubble: var(--ai-assistant-bot-bubble, rgba(255, 255, 255, 0.04));
    --ai-radius: 12px;

    position: fixed;
    z-index: 9999;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    font-size: 13px;
    line-height: 1.5;
    color: var(--ai-text);
    touch-action: none;
    user-select: none;
  }

  :host([position="bottom-right"]) { right: 20px; bottom: 20px; }
  :host([position="bottom-left"]) { left: 20px; bottom: 20px; }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  /* ── Speech Bubble (always visible, cycling phrases) ── */
  .speech-bubble {
    position: relative;
    background: var(--ai-bg);
    border: 1px solid var(--ai-border);
    border-radius: var(--ai-radius);
    padding: 8px 14px;
    margin-bottom: 15px;
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    box-shadow: 0 2px 12px rgba(0,0,0,0.3);
    max-width: 280px;
    margin-left: auto;
    margin-right: auto;
  }
  .speech-bubble::after {
    content: '';
    position: absolute;
    bottom: -8px;
    left: 50%;
    transform: translateX(-50%);
    width: 0;
    height: 0;
    border-left: 8px solid transparent;
    border-right: 8px solid transparent;
    border-top: 8px solid var(--ai-bg);
    filter: drop-shadow(0 1px 1px rgba(0,0,0,0.2));
  }
  .speech-text {
    font-size: 13px;
    color: var(--ai-text);
    transition: opacity 0.3s ease;
    display: block;
    text-align: center;
  }

  /* ── Mascot Row (character + action buttons) ── */
  .mascot-row {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0;
  }

  /* ── Mascot Character ── */
  .mascot {
    width: 255px;
    height: 255px;
    cursor: grab;
    touch-action: none;
    display: flex;
    align-items: center;
    justify-content: center;
    position: relative;
  }

  .mascot-canvas {
    width: 255px;
    height: 255px;
    user-select: none;
    pointer-events: none;
  }

  /* ── Action Buttons (right side of mascot) ── */
  .action-buttons {
    display: flex;
    flex-direction: column;
    gap: 6px;
    align-self: center;
  }
  .action-btn {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    border: 1px solid var(--ai-border);
    background: var(--ai-bg);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    color: var(--ai-text-dim);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 18px;
    transition: transform 0.15s, color 0.15s, background 0.15s, box-shadow 0.15s;
    box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    letter-spacing: 1px;
  }
  .action-btn:hover {
    transform: scale(1.1);
    color: var(--ai-accent);
    background: var(--ai-accent-bg);
    box-shadow: 0 2px 12px rgba(180, 190, 254, 0.2);
  }
  .action-btn.active {
    color: var(--ai-accent);
    background: var(--ai-accent-bg);
  }

  /* ── Quick Input (below mascot) ── */
  .quick-input {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-top: 10px;
    max-width: 320px;
    margin-left: auto;
    margin-right: auto;
  }
  .quick-input.hidden { display: none; }

  .quick-input input {
    flex: 1;
    height: 36px;
    background: var(--ai-bg);
    border: 1px solid var(--ai-border);
    border-radius: 18px;
    padding: 0 14px;
    color: var(--ai-text);
    font-size: 13px;
    outline: none;
    font-family: inherit;
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    box-shadow: 0 2px 8px rgba(0,0,0,0.2);
  }
  .quick-input input::placeholder { color: var(--ai-text-dim); }
  .quick-input input:focus { border-color: var(--ai-accent); }

  .quick-input .send-btn {
    width: 36px;
    height: 36px;
    flex-shrink: 0;
    border: none;
    border-radius: 50%;
    background: var(--ai-bg);
    border: 1px solid var(--ai-border);
    color: var(--ai-text-dim);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 14px;
    transition: background 0.15s, color 0.15s;
    box-shadow: 0 2px 8px rgba(0,0,0,0.2);
  }
  .quick-input .send-btn.active {
    background: var(--ai-accent-bg);
    color: var(--ai-accent);
  }
  .quick-input .send-btn:disabled { cursor: default; opacity: 0.5; }

  /* ── Responsive ── */
  @media (max-width: 480px) {
    .mascot { width: 200px; height: 200px; }
    .mascot-canvas { width: 200px; height: 200px; }
    .quick-input { max-width: 240px; }
  }
`;
