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

import { SpriteAnimator } from "@workshop/live2d-core";
import { startStream } from "./stream-handler";
import { STYLES } from "./styles";
import type { ChatMessage, MascotState } from "./types";

const DEFAULT_GREETING = "有什麼可以幫忙的嗎？";
const DEFAULT_MASCOT_BASE = "/static/mascot";
const PHRASE_INTERVAL = 6000;

const IDLE_PHRASES = [
  "有什麼可以幫忙的嗎？",
  "今天想做什麼呢？",
  "需要查什麼資料嗎？",
  "隨時可以問我問題喔！",
  "正在待命中...",
  "要不要看看今天的簡報？",
  "有新的想法想記錄嗎？",
  "我可以幫你搜尋記憶庫！",
];

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
    "mascot-base",
  ];

  private shadow: ShadowRoot;
  private animator: SpriteAnimator | null = null;
  private messages: ChatMessage[] = [];
  private isStreaming = false;
  private mascotState: MascotState = "idle";
  private streamingContent = "";
  private abortController: AbortController | null = null;
  private phraseTimer: ReturnType<typeof setInterval> | null = null;
  private isDragging = false;
  private dragOffset = { x: 0, y: 0 };

  // DOM refs
  private mascotEl!: HTMLDivElement;
  private speechTextEl!: HTMLSpanElement;
  private quickInputWrap!: HTMLDivElement;
  private quickInputEl!: HTMLInputElement;
  private quickSendBtn!: HTMLButtonElement;
  private chatToggleBtn!: HTMLButtonElement;

  constructor() {
    super();
    this.shadow = this.attachShadow({ mode: "open" });
  }

  connectedCallback() {
    this.render();
    this.bindEvents();
    this.setMascotState("idle");
    this.startPhraseRotation();

    const canvas = this.shadow.querySelector('.mascot-canvas') as HTMLCanvasElement;
    if (canvas) {
      this.animator = new SpriteAnimator({
        canvas,
        width: 510,
        height: 510,
        layerBasePath: `${this.mascotBase}/layers`,
      });
      // Fire-and-forget async init — PixiJS loads layers then starts rendering.
      this.animator.init().catch((err) =>
        console.error("[ai-assistant] SpriteAnimator init failed:", err)
      );

      // Mouse tracking
      document.addEventListener('mousemove', this._onMouseMove);
    }

    this.dispatchEvent(new CustomEvent("assistant-ready"));
  }

  private _onMouseMove = (e: MouseEvent) => {
    this.animator?.setMousePosition(e.clientX, e.clientY);
  };

  disconnectedCallback() {
    this.abortController?.abort();
    if (this.phraseTimer) clearInterval(this.phraseTimer);
    this.animator?.destroy();
    this.animator = null;
    document.removeEventListener('mousemove', this._onMouseMove);
  }

  // ── Public API ──

  say(text: string) {
    this.setSpeechText(text);
  }

  open() {
    this.showInput();
  }

  close() {
    this.hideInput();
  }

  toggle() {
    this.toggleInput();
  }

  private toggleInput() {
    const isHidden = this.quickInputWrap.classList.contains("hidden");
    if (isHidden) this.showInput();
    else this.hideInput();
  }

  private showInput() {
    this.quickInputWrap.classList.remove("hidden");
    this.chatToggleBtn.classList.add("active");
    requestAnimationFrame(() => this.quickInputEl?.focus());
    this.dispatchEvent(new CustomEvent("assistant-open"));
  }

  private hideInput() {
    this.quickInputWrap.classList.add("hidden");
    this.chatToggleBtn.classList.remove("active");
    this.dispatchEvent(new CustomEvent("assistant-close"));
  }

  setModule(name: string) {
    this.setAttribute("module", name);
  }

  // ── Internal getters ──

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

  private get mascotBase(): string {
    return this.getAttribute("mascot-base") ?? DEFAULT_MASCOT_BASE;
  }

  // ── Render ──

  private render() {
    const style = document.createElement("style");
    style.textContent = STYLES;

    const root = document.createElement("div");
    root.className = "assistant-root";
    root.innerHTML = `
      <div class="speech-bubble">
        <span class="speech-text">${this.greeting}</span>
      </div>

      <div class="mascot-row">
        <div class="mascot">
          <canvas class="mascot-canvas" width="510" height="510"></canvas>
        </div>
        <div class="action-buttons">
          <button class="action-btn chat-toggle" aria-label="展開輸入框" title="展開輸入框">⋯</button>
        </div>
      </div>

      <div class="quick-input hidden">
        <input type="text" placeholder="輸入問題..." aria-label="快速提問" />
        <button class="send-btn" disabled aria-label="送出">↑</button>
      </div>
    `;

    this.shadow.appendChild(style);
    this.shadow.appendChild(root);

    // Cache DOM refs
    this.mascotEl = this.shadow.querySelector(".mascot")!;
    this.speechTextEl = this.shadow.querySelector(".speech-text")!;
    this.quickInputWrap = this.shadow.querySelector(".quick-input")!;
    this.quickInputEl = this.shadow.querySelector(".quick-input input")!;
    this.quickSendBtn = this.shadow.querySelector(".quick-input .send-btn")!;
    this.chatToggleBtn = this.shadow.querySelector(".chat-toggle")!;
  }

  // ── Events ──

  private bindEvents() {
    // ⋯ button → toggle input box visibility
    this.chatToggleBtn.addEventListener("click", () => this.toggleInput());

    // Click mascot → change phrase (use pointerup to avoid drag conflict)
    let mascotPointerStart = { x: 0, y: 0 };
    this.mascotEl.addEventListener("pointerdown", (e) => {
      mascotPointerStart = { x: e.clientX, y: e.clientY };
    });
    this.mascotEl.addEventListener("pointerup", (e) => {
      const dx = Math.abs(e.clientX - mascotPointerStart.x);
      const dy = Math.abs(e.clientY - mascotPointerStart.y);
      if (dx < 5 && dy < 5 && this.mascotState === "idle") {
        const phrase = IDLE_PHRASES[Math.floor(Math.random() * IDLE_PHRASES.length)];
        this.setSpeechText(phrase);
      }
    });

    // Quick input
    this.bindInputPair(this.quickInputEl, this.quickSendBtn);

    // Drag support
    this.initDrag();

    // Keyboard shortcut: Cmd/Ctrl+Shift+A
    document.addEventListener("keydown", (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === "a") {
        e.preventDefault();
        this.toggleInput();
      }
    });
  }

  private initDrag() {
    const host = this as HTMLElement;
    let startX = 0;
    let startY = 0;
    let pointerId = -1;
    let captured = false;

    const onPointerDown = (e: PointerEvent) => {
      const target = e.composedPath()[0] as HTMLElement;
      if (target.tagName === "INPUT" || target.tagName === "BUTTON") return;

      this.isDragging = false;
      captured = false;
      pointerId = e.pointerId;
      startX = e.clientX;
      startY = e.clientY;

      const rect = host.getBoundingClientRect();
      this.dragOffset.x = e.clientX - rect.left;
      this.dragOffset.y = e.clientY - rect.top;

      // Don't capture yet — let click events flow normally
      document.addEventListener("pointermove", onPointerMove);
      document.addEventListener("pointerup", onPointerUp);
    };

    const onPointerMove = (e: PointerEvent) => {
      if (e.pointerId !== pointerId) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      if (!this.isDragging && Math.abs(dx) < 6 && Math.abs(dy) < 6) return;

      // First real movement — now capture
      if (!captured) {
        try { host.setPointerCapture(pointerId); } catch { /* ok */ }
        captured = true;
      }
      this.isDragging = true;

      host.style.position = "fixed";
      host.style.left = `${e.clientX - this.dragOffset.x}px`;
      host.style.top = `${e.clientY - this.dragOffset.y}px`;
      host.style.right = "auto";
      host.style.bottom = "auto";
    };

    const onPointerUp = (e: PointerEvent) => {
      if (e.pointerId !== pointerId) return;
      document.removeEventListener("pointermove", onPointerMove);
      document.removeEventListener("pointerup", onPointerUp);
      if (captured) {
        try { host.releasePointerCapture(pointerId); } catch { /* ok */ }
      }
      if (this.isDragging) {
        setTimeout(() => { this.isDragging = false; }, 50);
      }
    };

    host.addEventListener("pointerdown", onPointerDown);
  }

  private bindInputPair(input: HTMLInputElement, btn: HTMLButtonElement) {
    input.addEventListener("input", () => {
      const hasText = input.value.trim().length > 0;
      btn.disabled = !hasText;
      btn.classList.toggle("active", hasText);
    });

    input.addEventListener("keydown", (e: KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        this.handleSend(input, btn);
      }
    });

    btn.addEventListener("click", () => this.handleSend(input, btn));
  }

  // ── Send ──

  private handleSend(input: HTMLInputElement, btn: HTMLButtonElement) {
    const text = input.value.trim();
    if (!text || this.isStreaming) return;

    this.messages.push({ id: `msg-${Date.now()}`, role: "user", content: text, timestamp: Date.now() });
    input.value = "";
    btn.disabled = true;
    btn.classList.remove("active");

    this.sendToApi(text);
  }

  private sendToApi(message: string) {
    this.isStreaming = true;
    this.streamingContent = "";
    this.setMascotState("thinking");
    this.setSpeechText("思考中...");

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
        this.setSpeechText("思考中...");
      },

      onContent: (text, isDelta) => {
        if (isDelta) {
          this.streamingContent += text;
        } else {
          this.streamingContent = text;
        }
        this.setMascotState("speaking");
        // Show streaming content in speech bubble (truncate for display)
        const preview =
          this.streamingContent.length > 60
            ? this.streamingContent.slice(0, 60) + "..."
            : this.streamingContent;
        this.setSpeechText(preview);
      },

      onError: (msg) => {
        this.setMascotState("idle");
        this.setSpeechText(msg);
      },

      onDone: () => {
        this.isStreaming = false;
        this.setMascotState("idle");
        this.abortController = null;

        // Show final answer in speech bubble (truncated)
        if (this.streamingContent) {
          const final =
            this.streamingContent.length > 80
              ? this.streamingContent.slice(0, 80) + "..."
              : this.streamingContent;
          this.setSpeechText(final);
          this.messages.push({
            id: `msg-${Date.now()}`,
            role: "assistant",
            content: this.streamingContent,
            timestamp: Date.now(),
          });
        }

        // Resume phrase rotation after 10s
        setTimeout(() => this.startPhraseRotation(), 10000);

        this.dispatchEvent(
          new CustomEvent("assistant-message", {
            detail: { content: this.streamingContent },
          }),
        );
      },
    });
  }

  // ── Mascot State ──

  private setMascotState(state: MascotState) {
    if (this.mascotState === state) return;
    this.mascotState = state;

    if (state !== "idle") {
      this.stopPhraseRotation();
    }

    this.animator?.setState(state);
  }

  // ── Speech Bubble ──

  private setSpeechText(text: string) {
    if (!this.speechTextEl) return;
    this.speechTextEl.style.opacity = "0";
    setTimeout(() => {
      this.speechTextEl.textContent = text;
      this.speechTextEl.style.opacity = "1";
    }, 200);
  }

  private startPhraseRotation() {
    this.stopPhraseRotation();
    this.phraseTimer = setInterval(() => {
      if (this.mascotState !== "idle") return;
      const phrase =
        IDLE_PHRASES[Math.floor(Math.random() * IDLE_PHRASES.length)];
      this.setSpeechText(phrase);
    }, PHRASE_INTERVAL);
  }

  private stopPhraseRotation() {
    if (this.phraseTimer) {
      clearInterval(this.phraseTimer);
      this.phraseTimer = null;
    }
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
