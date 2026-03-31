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

  .assistant-root {
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
  }

  /* ── Speech Bubble — absolutely positioned above mascot ── */
  .speech-bubble {
    position: absolute;
    bottom: 100%;
    left: 50%;
    transform: translateX(-50%);
    margin-bottom: 8px;
    background: var(--ai-bg);
    border: 1px solid var(--ai-border);
    border-radius: var(--ai-radius);
    padding: 8px 14px;
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    box-shadow: 0 2px 12px rgba(0,0,0,0.3);
    max-width: 280px;
    width: max-content;
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
    white-space: pre-wrap;
    word-break: break-word;
  }

  /* ── State-colored speech bubble ── */
  .speech-bubble.thinking {
    border-color: rgba(180, 190, 254, 0.4);
    box-shadow: 0 2px 16px rgba(180, 190, 254, 0.15), 0 0 0 1px rgba(180, 190, 254, 0.1);
  }
  .speech-bubble.thinking::after {
    border-top-color: var(--ai-bg);
  }
  .speech-bubble.streaming {
    border-color: rgba(166, 227, 161, 0.35);
    box-shadow: 0 2px 12px rgba(166, 227, 161, 0.1);
  }

  /* ── Markdown rendered content in speech bubble ── */
  .speech-text p { margin: 0 0 0.4em; }
  .speech-text p:last-child { margin-bottom: 0; }
  .speech-text a {
    color: var(--ai-accent);
    text-decoration: none;
    border-bottom: 1px dotted var(--ai-accent);
  }
  .speech-text a:hover { opacity: 0.8; }
  .speech-text code {
    background: rgba(255,255,255,0.06);
    padding: 1px 4px;
    border-radius: 3px;
    font-size: 12px;
  }
  .speech-text ul, .speech-text ol {
    padding-left: 1.2em;
    margin: 0.3em 0;
  }
  .speech-text li { margin: 0.15em 0; }

  /* ── Loading spinner (above text, inside bubble) ── */
  .speech-bubble.thinking .speech-text {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
  }
  .speech-bubble.thinking .speech-text::before {
    content: '';
    flex-shrink: 0;
    width: 16px;
    height: 16px;
    border: 2.5px solid rgba(180, 190, 254, 0.25);
    border-top-color: var(--ai-accent);
    border-radius: 50%;
    animation: ai-spin 0.7s linear infinite;
  }
  @keyframes ai-spin {
    to { transform: rotate(360deg); }
  }

  /* Pulse glow on thinking bubble */
  .speech-bubble.thinking {
    animation: ai-pulse 2s ease-in-out infinite;
  }
  @keyframes ai-pulse {
    0%, 100% { box-shadow: 0 2px 16px rgba(180, 190, 254, 0.15), 0 0 0 1px rgba(180, 190, 254, 0.1); }
    50% { box-shadow: 0 2px 20px rgba(180, 190, 254, 0.3), 0 0 0 1px rgba(180, 190, 254, 0.2); }
  }
  .speech-bubble.streaming {
    padding-right: 6px;
  }
  .speech-bubble.streaming .speech-text {
    text-align: left;
    max-height: 9em;
    overflow-y: auto;
    padding-right: 6px;
    scrollbar-width: thin;
    scrollbar-color: rgba(255,255,255,0.2) transparent;
  }
  .speech-bubble.streaming .speech-text::-webkit-scrollbar {
    width: 4px;
  }
  .speech-bubble.streaming .speech-text::-webkit-scrollbar-track {
    background: transparent;
  }
  .speech-bubble.streaming .speech-text::-webkit-scrollbar-thumb {
    background: rgba(255,255,255,0.2);
    border-radius: 2px;
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
