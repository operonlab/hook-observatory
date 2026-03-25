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
  }

  :host([position="bottom-right"]) { right: 20px; bottom: 20px; }
  :host([position="bottom-left"]) { left: 20px; bottom: 20px; }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  /* ── FAB (floating action button) ── */
  .fab {
    width: 56px;
    height: 56px;
    border-radius: 50%;
    border: 1px solid var(--ai-border);
    background: var(--ai-bg);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 4px 20px rgba(0,0,0,0.4);
    transition: transform 0.2s, box-shadow 0.2s;
    overflow: hidden;
    position: relative;
  }
  .fab:hover {
    transform: scale(1.08);
    box-shadow: 0 6px 28px rgba(0,0,0,0.5);
  }
  .fab.hidden { display: none; }

  .fab-icon {
    width: 48px;
    height: 48px;
    object-fit: contain;
    user-select: none;
    pointer-events: none;
  }

  /* Mascot animations */
  .fab[data-state="idle"] .fab-icon {
    animation: float 3s ease-in-out infinite;
  }
  .fab[data-state="thinking"] .fab-icon {
    animation: pulse 1.5s ease-in-out infinite;
  }
  .fab[data-state="speaking"] .fab-icon {
    animation: bounce 0.6s ease-in-out infinite;
  }
  .fab[data-state="wave"] .fab-icon {
    animation: wave 0.8s ease-in-out;
  }

  @keyframes float {
    0%, 100% { transform: translateY(0); }
    50% { transform: translateY(-4px); }
  }
  @keyframes pulse {
    0%, 100% { transform: scale(1); opacity: 1; }
    50% { transform: scale(1.1); opacity: 0.8; }
  }
  @keyframes bounce {
    0%, 100% { transform: translateY(0); }
    50% { transform: translateY(-3px); }
  }
  @keyframes wave {
    0% { transform: rotate(0deg); }
    25% { transform: rotate(15deg); }
    50% { transform: rotate(-10deg); }
    75% { transform: rotate(8deg); }
    100% { transform: rotate(0deg); }
  }

  /* ── Chat Panel ── */
  .panel {
    position: absolute;
    bottom: 68px;
    width: 360px;
    max-height: 520px;
    background: var(--ai-bg);
    border: 1px solid var(--ai-border);
    border-radius: var(--ai-radius);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    box-shadow: 0 8px 40px rgba(0,0,0,0.5);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    transform-origin: bottom right;
    transition: opacity 0.25s, transform 0.25s;
  }
  :host([position="bottom-right"]) .panel { right: 0; }
  :host([position="bottom-left"]) .panel { left: 0; transform-origin: bottom left; }
  .panel.hidden {
    opacity: 0;
    transform: scale(0.95) translateY(8px);
    pointer-events: none;
  }
  .panel.visible {
    opacity: 1;
    transform: scale(1) translateY(0);
  }

  /* ── Panel Header ── */
  .panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 14px;
    border-bottom: 1px solid var(--ai-border);
    flex-shrink: 0;
  }
  .panel-title {
    font-size: 12px;
    font-weight: 600;
    color: var(--ai-text-dim);
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .panel-title .mascot-small {
    width: 24px;
    height: 24px;
    object-fit: contain;
  }
  .close-btn {
    width: 24px;
    height: 24px;
    border: none;
    background: none;
    color: var(--ai-text-dim);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 4px;
    font-size: 14px;
  }
  .close-btn:hover { color: var(--ai-text); background: var(--ai-surface); }

  /* ── Messages Area ── */
  .messages {
    flex: 1;
    overflow-y: auto;
    padding: 12px 14px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    min-height: 200px;
  }
  .messages::-webkit-scrollbar { width: 4px; }
  .messages::-webkit-scrollbar-thumb {
    background: rgba(255,255,255,0.1);
    border-radius: 2px;
  }

  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    gap: 8px;
    opacity: 0.4;
    text-align: center;
  }
  .empty-state .mascot-large {
    width: 80px;
    height: 80px;
    object-fit: contain;
  }
  .empty-state p { font-size: 11px; color: var(--ai-text-dim); }

  /* ── Message Bubbles ── */
  .msg {
    display: flex;
    flex-direction: column;
    gap: 3px;
    max-width: 85%;
  }
  .msg.user { align-self: flex-end; }
  .msg.assistant { align-self: flex-start; }

  .msg-bubble {
    padding: 8px 12px;
    font-size: 13px;
    line-height: 1.55;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .msg.user .msg-bubble {
    background: var(--ai-user-bubble);
    border-radius: 12px 12px 2px 12px;
  }
  .msg.assistant .msg-bubble {
    background: var(--ai-bot-bubble);
    border-radius: 12px 12px 12px 2px;
  }
  .msg-time {
    font-size: 10px;
    color: var(--ai-text-dim);
    padding: 0 4px;
    opacity: 0.6;
  }
  .msg.user .msg-time { text-align: right; }

  /* Markdown in messages */
  .msg-bubble code {
    background: rgba(255,255,255,0.08);
    padding: 1px 4px;
    border-radius: 3px;
    font-size: 12px;
    font-family: 'SF Mono', 'Fira Code', monospace;
  }
  .msg-bubble pre {
    background: rgba(0,0,0,0.3);
    padding: 8px;
    border-radius: 6px;
    overflow-x: auto;
    margin: 6px 0;
  }
  .msg-bubble pre code {
    background: none;
    padding: 0;
  }
  .msg-bubble a {
    color: var(--ai-accent);
    text-decoration: none;
  }
  .msg-bubble a:hover { text-decoration: underline; }
  .msg-bubble ul, .msg-bubble ol {
    padding-left: 18px;
    margin: 4px 0;
  }
  .msg-bubble p { margin-bottom: 6px; }
  .msg-bubble p:last-child { margin-bottom: 0; }

  /* Streaming indicator */
  .streaming-dot {
    display: inline-block;
    width: 6px;
    height: 6px;
    background: var(--ai-accent);
    border-radius: 50%;
    animation: blink 1s infinite;
    margin-left: 4px;
    vertical-align: middle;
  }
  @keyframes blink {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.3; }
  }

  /* ── Input Area ── */
  .input-area {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    border-top: 1px solid var(--ai-border);
    flex-shrink: 0;
  }
  .input-area input {
    flex: 1;
    height: 34px;
    background: var(--ai-surface);
    border: 1px solid var(--ai-border);
    border-radius: 8px;
    padding: 0 10px;
    color: var(--ai-text);
    font-size: 13px;
    outline: none;
    font-family: inherit;
  }
  .input-area input::placeholder { color: var(--ai-text-dim); }
  .input-area input:focus { border-color: var(--ai-accent); }

  .send-btn {
    width: 34px;
    height: 34px;
    flex-shrink: 0;
    border: none;
    border-radius: 8px;
    background: var(--ai-surface);
    color: var(--ai-text-dim);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 14px;
    transition: background 0.15s, color 0.15s;
  }
  .send-btn.active {
    background: var(--ai-accent-bg);
    color: var(--ai-accent);
  }
  .send-btn:disabled { cursor: default; opacity: 0.5; }

  /* ── Responsive ── */
  @media (max-width: 480px) {
    .panel {
      width: calc(100vw - 32px);
      max-height: 70vh;
      bottom: 68px;
    }
    :host([position="bottom-right"]) .panel { right: -4px; }
    :host([position="bottom-left"]) .panel { left: -4px; }
  }
`;
