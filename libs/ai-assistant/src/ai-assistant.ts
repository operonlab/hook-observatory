/**
 * <ai-assistant> Web Component
 *
 * A floating AI chat widget with SSE streaming, Shadow DOM isolation,
 * and customizable mascot character.
 *
 * Usage:
 *   <ai-assistant mode="workshop" api-url="/api/assistant/chat" />
 *   <ai-assistant mode="blog" api-url="/api/assistant/chat" />
 */

import { renderMarkdown } from "./markdown";
import { startStream } from "./stream-handler";
import { STYLES } from "./styles";
import type { ChatMessage, MascotState } from "./types";

const DEFAULT_MASCOT = "✨";
const DEFAULT_GREETING = "有什麼我可以幫忙的嗎？";

let msgIdCounter = 0;

export class AiAssistantElement extends HTMLElement {
  static observedAttributes = [
    "mode",
    "api-url",
    "position",
    "theme",
    "greeting",
    "language",
    "module",
    "mascot-emoji",
  ];

  private shadow: ShadowRoot;
  private messages: ChatMessage[] = [];
  private isOpen = false;
  private isStreaming = false;
  private mascotState: MascotState = "idle";
  private streamingContent = "";
  private abortController: AbortController | null = null;

  // DOM refs
  private fab!: HTMLButtonElement;
  private panel!: HTMLDivElement;
  private messagesEl!: HTMLDivElement;
  private inputEl!: HTMLInputElement;
  private sendBtn!: HTMLButtonElement;

  constructor() {
    super();
    this.shadow = this.attachShadow({ mode: "open" });
  }

  connectedCallback() {
    this.render();
    this.bindEvents();

    // Play wave animation on first appearance
    this.setMascotState("wave");
    setTimeout(() => this.setMascotState("idle"), 1200);

    this.dispatchEvent(new CustomEvent("assistant-ready"));
  }

  disconnectedCallback() {
    this.abortController?.abort();
  }

  attributeChangedCallback(name: string, _old: string | null, val: string | null) {
    if (name === "position") {
      // Position is handled by :host CSS
    } else if (name === "mascot-emoji") {
      this.updateMascotDisplay();
    }
  }

  // ── Public API ──

  say(text: string) {
    this.addMessage("assistant", text);
  }

  open() {
    this.isOpen = true;
    this.updatePanelVisibility();
    this.inputEl?.focus();
    this.dispatchEvent(new CustomEvent("assistant-open"));
  }

  close() {
    this.isOpen = false;
    this.updatePanelVisibility();
    this.dispatchEvent(new CustomEvent("assistant-close"));
  }

  toggle() {
    if (this.isOpen) this.close();
    else this.open();
  }

  setModule(name: string) {
    this.setAttribute("module", name);
  }

  // ── Internal ──

  private get apiUrl(): string {
    return this.getAttribute("api-url") ?? "/api/assistant/chat";
  }

  private get mode(): string {
    return this.getAttribute("mode") ?? "workshop";
  }

  private get module(): string | null {
    return this.getAttribute("module");
  }

  private get greeting(): string {
    return this.getAttribute("greeting") ?? DEFAULT_GREETING;
  }

  private get mascotEmoji(): string {
    return this.getAttribute("mascot-emoji") ?? DEFAULT_MASCOT;
  }

  private render() {
    const style = document.createElement("style");
    style.textContent = STYLES;

    const container = document.createElement("div");
    container.innerHTML = `
      <button class="fab" data-state="idle" aria-label="開啟 AI 助手">
        <span class="fab-icon">${this.mascotEmoji}</span>
      </button>

      <div class="panel hidden" role="dialog" aria-label="AI 助手對話">
        <div class="panel-header">
          <div class="panel-title">
            <span class="mascot-small">${this.mascotEmoji}</span>
            <span>AI 助手</span>
          </div>
          <button class="close-btn" aria-label="關閉">✕</button>
        </div>

        <div class="messages">
          <div class="empty-state">
            <span class="mascot-large">${this.mascotEmoji}</span>
            <p>${this.greeting}</p>
          </div>
        </div>

        <div class="input-area">
          <input type="text" placeholder="輸入訊息..." aria-label="訊息輸入" />
          <button class="send-btn" disabled aria-label="送出">↑</button>
        </div>
      </div>
    `;

    this.shadow.appendChild(style);
    this.shadow.appendChild(container);

    // Cache DOM refs
    this.fab = this.shadow.querySelector(".fab")!;
    this.panel = this.shadow.querySelector(".panel")!;
    this.messagesEl = this.shadow.querySelector(".messages")!;
    this.inputEl = this.shadow.querySelector("input")!;
    this.sendBtn = this.shadow.querySelector(".send-btn")!;
  }

  private bindEvents() {
    this.fab.addEventListener("click", () => this.toggle());

    this.shadow.querySelector(".close-btn")!.addEventListener("click", () => this.close());

    this.inputEl.addEventListener("input", () => {
      const hasText = this.inputEl.value.trim().length > 0;
      this.sendBtn.disabled = !hasText;
      this.sendBtn.classList.toggle("active", hasText);
    });

    this.inputEl.addEventListener("keydown", (e: KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        this.handleSend();
      }
    });

    this.sendBtn.addEventListener("click", () => this.handleSend());

    // Keyboard shortcut: Cmd/Ctrl+Shift+A
    document.addEventListener("keydown", (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === "a") {
        e.preventDefault();
        this.toggle();
      }
    });
  }

  private handleSend() {
    const text = this.inputEl.value.trim();
    if (!text || this.isStreaming) return;

    this.addMessage("user", text);
    this.inputEl.value = "";
    this.sendBtn.disabled = true;
    this.sendBtn.classList.remove("active");

    this.sendToApi(text);
  }

  private sendToApi(message: string) {
    this.isStreaming = true;
    this.streamingContent = "";
    this.setMascotState("thinking");

    // Create a placeholder assistant message
    const assistantMsgId = this.addMessage("assistant", "");
    const bubbleEl = this.shadow.querySelector(`[data-msg-id="${assistantMsgId}"] .msg-bubble`);

    if (bubbleEl) {
      bubbleEl.innerHTML = '<span class="streaming-dot"></span>';
    }

    const body: Record<string, unknown> = {
      message,
      mode: this.mode,
    };
    if (this.mode === "workshop" && this.module) {
      body.module = this.module;
    }

    this.abortController = startStream(this.apiUrl, body, {
      onThinking: () => {
        this.setMascotState("thinking");
      },

      onContent: (text, isDelta) => {
        if (isDelta) {
          this.streamingContent += text;
        } else {
          this.streamingContent = text;
        }
        this.setMascotState("speaking");

        if (bubbleEl) {
          bubbleEl.innerHTML = renderMarkdown(this.streamingContent);
          this.scrollToBottom();
        }
      },

      onError: (msg) => {
        this.setMascotState("idle");
        if (bubbleEl) {
          bubbleEl.innerHTML = `<em style="opacity:0.6">${msg}</em>`;
        }
      },

      onDone: () => {
        this.isStreaming = false;
        this.setMascotState("idle");
        this.abortController = null;

        // Update the message content in our model
        const assistantMsg = this.messages.find((m) => m.id === assistantMsgId);
        if (assistantMsg) {
          assistantMsg.content = this.streamingContent;
        }

        // Final render with markdown
        if (bubbleEl && this.streamingContent) {
          bubbleEl.innerHTML = renderMarkdown(this.streamingContent);
        }

        this.dispatchEvent(
          new CustomEvent("assistant-message", {
            detail: { content: this.streamingContent },
          }),
        );

        this.scrollToBottom();
      },
    });
  }

  private addMessage(role: "user" | "assistant", content: string): string {
    const id = `msg-${Date.now()}-${++msgIdCounter}`;
    const msg: ChatMessage = { id, role, content, timestamp: Date.now() };
    this.messages.push(msg);

    // Remove empty state
    const emptyState = this.messagesEl.querySelector(".empty-state");
    if (emptyState) emptyState.remove();

    // Create DOM
    const msgEl = document.createElement("div");
    msgEl.className = `msg ${role}`;
    msgEl.setAttribute("data-msg-id", id);

    const bubble = document.createElement("div");
    bubble.className = "msg-bubble";
    if (content) {
      bubble.innerHTML = role === "assistant" ? renderMarkdown(content) : this.escapeHtml(content);
    }

    const time = document.createElement("span");
    time.className = "msg-time";
    time.textContent = new Date().toLocaleTimeString("zh-TW", {
      hour: "2-digit",
      minute: "2-digit",
    });

    msgEl.appendChild(bubble);
    msgEl.appendChild(time);
    this.messagesEl.appendChild(msgEl);
    this.scrollToBottom();

    return id;
  }

  private scrollToBottom() {
    requestAnimationFrame(() => {
      this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
    });
  }

  private setMascotState(state: MascotState) {
    this.mascotState = state;
    this.fab.setAttribute("data-state", state);
  }

  private updatePanelVisibility() {
    if (this.isOpen) {
      this.panel.classList.remove("hidden");
      this.panel.classList.add("visible");
      this.fab.classList.add("hidden");
      requestAnimationFrame(() => this.inputEl?.focus());
    } else {
      this.panel.classList.add("hidden");
      this.panel.classList.remove("visible");
      this.fab.classList.remove("hidden");
    }
  }

  private updateMascotDisplay() {
    const emoji = this.mascotEmoji;
    const fabIcon = this.shadow.querySelector(".fab-icon");
    const panelMascot = this.shadow.querySelector(".mascot-small");
    const emptyMascot = this.shadow.querySelector(".mascot-large");

    if (fabIcon) fabIcon.textContent = emoji;
    if (panelMascot) panelMascot.textContent = emoji;
    if (emptyMascot) emptyMascot.textContent = emoji;
  }

  private escapeHtml(text: string): string {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }
}

// Register the custom element
if (!customElements.get("ai-assistant")) {
  customElements.define("ai-assistant", AiAssistantElement);
}

// Re-export types for consumers
export type { ChatMessage, MascotState, StreamBlock } from "./types";
