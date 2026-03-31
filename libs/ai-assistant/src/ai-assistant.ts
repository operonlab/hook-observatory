/**
 * <ai-assistant> Web Component
 *
 * A floating AI chat widget with SSE streaming, Shadow DOM isolation,
 * and customizable mascot character.
 *
 * State management uses a Finite State Machine (FSM):
 *   idle → thinking → streaming → draining → idle
 *
 * Usage:
 *   <ai-assistant mode="workshop" api-url="/api/assistant/chat" />
 *   <ai-assistant mode="blog" api-url="/api/assistant/chat" />
 */

import { SpriteAnimator } from "@workshop/live2d-core";
import type { CubismRendererOptions } from "@workshop/live2d-core";
import { renderMarkdown } from "./markdown";
import { startStream } from "./stream-handler";
import { STYLES } from "./styles";
import type { ChatMessage, MascotState } from "./types";

interface MascotRenderer {
  init(): Promise<void>;
  destroy(): void;
  setState(state: MascotState): void;
  setMousePosition(x: number, y: number): void;
  setLipSync(amplitude: number): void;
}

/** Lazy-load CubismRenderer to keep engine out of main bundle */
async function createCubismRenderer(opts: CubismRendererOptions): Promise<MascotRenderer> {
  const { CubismRenderer } = await import("@workshop/live2d-core/cubism-entry");
  return new CubismRenderer(opts);
}

const DEFAULT_GREETING = "有什麼可以幫忙的嗎？";
const DEFAULT_MASCOT_BASE = "/static/mascot";
const PHRASE_INTERVAL = 6000;
// No safety timeout — only user-initiated dismiss returns to idle

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

// ---------------------------------------------------------------------------
// FSM types
// ---------------------------------------------------------------------------
type FsmState = "idle" | "thinking" | "streaming" | "draining";
type FsmEvent =
  | "SEND"
  | "SSE_THINKING"
  | "SSE_PROGRESS"
  | "SSE_CONTENT"
  | "SSE_ERROR"
  | "SSE_DONE"
  | "TW_CAUGHT_UP";

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
    "model-path",
  ];

  private shadow: ShadowRoot;
  private animator: MascotRenderer | null = null;
  private cubismAnimator: MascotRenderer | null = null;
  private spriteAnimator: MascotRenderer | null = null;
  private cubismCanvas: HTMLCanvasElement | null = null;
  private spriteCanvas: HTMLCanvasElement | null = null;
  private useCubism = false;
  private lipSyncRaf = 0;
  private speakingTimeout: ReturnType<typeof setTimeout> | null = null;
  private typewriterTimer: ReturnType<typeof setTimeout> | null = null;
  private typewriterQueue = "";
  private typewriterShown = "";
  private messages: ChatMessage[] = [];
  private fsmState: FsmState = "idle";
  private mascotVisual: MascotState = "idle";
  private streamingContent = "";
  private abortController: AbortController | null = null;
  private sessionId = crypto.randomUUID().replace(/-/g, "").slice(0, 12);
  private phraseTimer: ReturnType<typeof setInterval> | null = null;
  private isDragging = false;
  private dragOffset = { x: 0, y: 0 };

  // DOM refs
  private mascotEl!: HTMLDivElement;
  private speechBubbleEl!: HTMLDivElement;
  private speechTextEl!: HTMLSpanElement;
  private quickInputWrap!: HTMLDivElement;
  private quickInputEl!: HTMLInputElement;
  private quickSendBtn!: HTMLButtonElement;
  private chatToggleBtn!: HTMLButtonElement;
  private switchBtn!: HTMLButtonElement;

  constructor() {
    super();
    this.shadow = this.attachShadow({ mode: "open" });
  }

  connectedCallback() {
    this.render();
    this.bindEvents();
    this._setMascotVisual("idle");
    this.startPhraseRotation();

    this.cubismCanvas = this.shadow.querySelector('.cubism-canvas') as HTMLCanvasElement;
    this.spriteCanvas = this.shadow.querySelector('.sprite-canvas') as HTMLCanvasElement;
    const modelPath = this.getAttribute("model-path");

    if (modelPath && this.cubismCanvas) {
      this.useCubism = true;
      this.cubismCanvas.style.display = "";
      this.spriteCanvas!.style.display = "none";
      createCubismRenderer({ canvas: this.cubismCanvas, width: 510, height: 510, modelPath })
        .then((r) => { this.cubismAnimator = r; this.animator = r; return r.init(); })
        .catch((err) => console.error("[ai-assistant] CubismRenderer init failed:", err));
    } else if (this.spriteCanvas) {
      this.useCubism = false;
      this.cubismCanvas!.style.display = "none";
      this.spriteCanvas.style.display = "";
      const r = new SpriteAnimator({ canvas: this.spriteCanvas, width: 510, height: 510, layerBasePath: `${this._mascotBase}/layers` });
      this.spriteAnimator = r;
      this.animator = r;
      r.init().catch((err) => console.error("[ai-assistant] SpriteAnimator init failed:", err));
    }

    document.addEventListener('mousemove', this._onMouseMove);

    this.dispatchEvent(new CustomEvent("assistant-ready"));
  }

  private _switchRenderer() {
    this.useCubism = !this.useCubism;

    if (this.useCubism) {
      this.cubismCanvas!.style.display = "";
      this.spriteCanvas!.style.display = "none";
      this.animator = this.cubismAnimator;
    } else {
      this.cubismCanvas!.style.display = "none";
      this.spriteCanvas!.style.display = "";
      if (!this.spriteAnimator && this.spriteCanvas) {
        const r = new SpriteAnimator({ canvas: this.spriteCanvas, width: 510, height: 510, layerBasePath: `${this._mascotBase}/layers` });
        this.spriteAnimator = r;
        r.init().catch((err) => console.error("[ai-assistant] SpriteAnimator init failed:", err));
      }
      this.animator = this.spriteAnimator;
    }

    this.switchBtn.title = this.useCubism ? "切換為精靈模式" : "切換為 Live2D 模式";
  }

  // ---------------------------------------------------------------------------
  // FSM — Finite State Machine
  // ---------------------------------------------------------------------------

  private transition(event: FsmEvent, payload?: any) {
    // SEND from any state → abort + restart
    if (event === "SEND") {
      this._enterThinking(payload as string);
      return;
    }

    switch (this.fsmState) {
      case "idle":
        // Only SEND is valid (handled above)
        break;

      case "thinking":
        if (event === "SSE_THINKING") { /* already thinking, no-op */ }
        else if (event === "SSE_PROGRESS") { this.setSpeechText(payload as string); }
        else if (event === "SSE_CONTENT") { this._enterStreaming(payload); }
        else if (event === "SSE_ERROR") { this._enterIdle({ error: payload as string }); }
        else if (event === "SSE_DONE") { this._enterIdle(); }
        break;

      case "streaming":
        if (event === "SSE_CONTENT") { this._onChunk(payload); }
        else if (event === "SSE_PROGRESS") { /* tool call mid-stream, ignore in UI */ }
        else if (event === "SSE_ERROR") { this._enterIdle({ error: payload as string }); }
        else if (event === "SSE_DONE") { this._enterDraining(); }
        break;

      case "draining":
        if (event === "TW_CAUGHT_UP") { this._enterIdle(); }
        break;
    }
  }

  // ── FSM enter actions ──

  private _enterIdle(opts?: { error?: string }) {
    this.fsmState = "idle";
    this._stopLipSync();
    this._stopTypewriter(); // shows full typewriterQueue text
    this._clearTimeouts();
    this.abortController = null;
    this._setMascotVisual("idle");

    if (opts?.error) {
      this.speechBubbleEl?.classList.remove("streaming", "thinking");
      this.setSpeechText(opts.error);
      this.startPhraseRotation();
    } else if (this.streamingContent) {
      // Keep the full text as typewriter displayed it — no truncation
      // Keep "streaming" class for left-aligned text
      this.messages.push({
        id: `msg-${Date.now()}`,
        role: "assistant",
        content: this.streamingContent,
        timestamp: Date.now(),
      });
      this.dispatchEvent(
        new CustomEvent("assistant-message", {
          detail: { content: this.streamingContent },
        }),
      );
      // Do NOT start phrase rotation — let the answer stay visible
    } else {
      this.speechBubbleEl?.classList.remove("streaming");
      this.startPhraseRotation();
    }
  }

  private _enterThinking(message: string) {
    // Cleanup previous
    this.abortController?.abort();
    this._stopLipSync();
    this._stopTypewriter();
    this._clearTimeouts();

    this.fsmState = "thinking";
    this.streamingContent = "";
    this.typewriterQueue = "";
    this.typewriterShown = "";
    this.stopPhraseRotation();

    // Visual
    this._setMascotVisual("thinking");
    this.speechBubbleEl?.classList.remove("streaming");
    this.speechBubbleEl?.classList.add("thinking");
    this.setSpeechText("思考中...");

    // Start stream — reuse persistent session_id (generated once per component lifecycle)
    const body: Record<string, unknown> = { message, mode: this._mode, session_id: this.sessionId };
    if (this._mode === "workshop" && this._module) {
      body.module = this._module;
    }

    this.abortController = startStream(this._apiUrl, body, {
      onThinking: () => this.transition("SSE_THINKING"),
      onProgress: (msg) => this.transition("SSE_PROGRESS", msg),
      onContent: (text, isDelta) => this.transition("SSE_CONTENT", { text, isDelta }),
      onError: (msg) => this.transition("SSE_ERROR", msg),
      onDone: () => this.transition("SSE_DONE"),
    });
  }

  private _enterStreaming(payload: { text: string; isDelta: boolean }) {
    this.fsmState = "streaming";

    // Visual
    this._setMascotVisual("speaking");
    this._startLipSync();
    this.speechBubbleEl?.classList.remove("thinking");
    this.speechBubbleEl?.classList.add("streaming");

    // Process first chunk
    this._appendContent(payload);
  }

  private _enterDraining() {
    this.fsmState = "draining";
    // Lip sync + typewriter continue running
    // If typewriter already caught up, go straight to idle
    if (!this.typewriterTimer && this.typewriterShown.length >= this.typewriterQueue.length) {
      this._enterIdle();
    }
  }

  private _onChunk(payload: { text: string; isDelta: boolean }) {
    this._appendContent(payload);
  }

  private _appendContent(payload: { text: string; isDelta: boolean }) {
    if (payload.isDelta) {
      this.streamingContent += payload.text;
    } else {
      this.streamingContent = payload.text;
    }
    this.typewriterQueue = this.streamingContent;
    this._startTypewriter();
  }

  // ---------------------------------------------------------------------------
  // Typewriter — additive, no truncation, 1 char per 40ms
  // ---------------------------------------------------------------------------

  private _startTypewriter() {
    if (this.typewriterTimer) return;
    const tick = () => {
      if (this.typewriterShown.length < this.typewriterQueue.length) {
        this.typewriterShown = this.typewriterQueue.slice(0, this.typewriterShown.length + 1);
        this.setSpeechText(this.typewriterShown, false);
        this.speechTextEl.scrollTop = this.speechTextEl.scrollHeight;
        this.typewriterTimer = setTimeout(tick, 40);
      } else {
        // Caught up — wait for more content or finalize if draining
        this.typewriterTimer = null;
        if (this.fsmState === "draining") {
          this.transition("TW_CAUGHT_UP");
        }
      }
    };
    tick();
  }

  private _stopTypewriter() {
    if (this.typewriterTimer) {
      clearTimeout(this.typewriterTimer);
      this.typewriterTimer = null;
    }
    if (this.typewriterQueue) {
      // Final render with markdown for proper formatting
      this.setSpeechText(this.typewriterQueue, false, true);
    }
    this.typewriterQueue = "";
    this.typewriterShown = "";
  }

  // ---------------------------------------------------------------------------
  // Lip sync
  // ---------------------------------------------------------------------------

  private _startLipSync() {
    if (this.lipSyncRaf) return;
    const loop = () => {
      const t = performance.now() / 1000;
      const amp = Math.abs(Math.sin(t * 8)) * 0.7 + Math.abs(Math.sin(t * 5.3)) * 0.3;
      this.animator?.setLipSync(amp);
      this.lipSyncRaf = requestAnimationFrame(loop);
    };
    this.lipSyncRaf = requestAnimationFrame(loop);
  }

  private _stopLipSync() {
    if (this.lipSyncRaf) {
      cancelAnimationFrame(this.lipSyncRaf);
      this.lipSyncRaf = 0;
    }
    this.animator?.setLipSync(0);
  }

  // ---------------------------------------------------------------------------
  // Timeouts
  // ---------------------------------------------------------------------------

  private _clearTimeouts() {
    if (this.speakingTimeout) { clearTimeout(this.speakingTimeout); this.speakingTimeout = null; }
  }

  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------

  private _onMouseMove = (e: MouseEvent) => {
    this.animator?.setMousePosition(e.clientX, e.clientY);
  };

  disconnectedCallback() {
    this.abortController?.abort();
    this._stopLipSync();
    this._stopTypewriter();
    this._clearTimeouts();
    if (this.phraseTimer) clearInterval(this.phraseTimer);
    this.fsmState = "idle";
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
  // NOTE: names MUST NOT match attribute names (mode, greeting, etc.)
  // because React 19 tries to set properties on custom elements and
  // getter-only props throw "Attempted to assign to readonly property".

  private get _apiUrl(): string {
    return this.getAttribute("api-url") ?? "/api/assistant/chat";
  }

  private get _mode(): string {
    return this.getAttribute("mode") ?? "workshop";
  }

  private get _module(): string | null {
    return this.getAttribute("module");
  }

  private get _greeting(): string {
    return this.getAttribute("greeting") ?? DEFAULT_GREETING;
  }

  private get _mascotBase(): string {
    return this.getAttribute("mascot-base") ?? DEFAULT_MASCOT_BASE;
  }

  // ── Render ──

  private render() {
    const style = document.createElement("style");
    style.textContent = STYLES;

    const root = document.createElement("div");
    root.className = "assistant-root";
    // Speech bubble is absolutely positioned above mascot-row,
    // so its height changes never push the mascot down.
    root.innerHTML = `
      <div class="speech-bubble">
        <span class="speech-text">${this._greeting}</span>
      </div>

      <div class="mascot-row">
        <div class="mascot">
          <canvas class="mascot-canvas cubism-canvas" width="510" height="510"></canvas>
          <canvas class="mascot-canvas sprite-canvas" width="510" height="510" style="display:none"></canvas>
        </div>
        <div class="action-buttons">
          <button class="action-btn mascot-switch" aria-label="切換角色" title="切換角色模式">🔄</button>
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
    this.speechBubbleEl = this.shadow.querySelector(".speech-bubble")!;
    this.speechTextEl = this.shadow.querySelector(".speech-text")!;
    this.quickInputWrap = this.shadow.querySelector(".quick-input")!;
    this.quickInputEl = this.shadow.querySelector(".quick-input input")!;
    this.quickSendBtn = this.shadow.querySelector(".quick-input .send-btn")!;
    this.chatToggleBtn = this.shadow.querySelector(".chat-toggle")!;
    this.switchBtn = this.shadow.querySelector(".mascot-switch")!;
    if (!this.getAttribute("model-path")) this.switchBtn.style.display = "none";
  }

  // ── Events ──

  private bindEvents() {
    this.chatToggleBtn.addEventListener("click", () => this.toggleInput());
    this.switchBtn.addEventListener("click", () => this._switchRenderer());

    // Click mascot → change phrase (use pointerup to avoid drag conflict)
    let mascotPointerStart = { x: 0, y: 0 };
    this.mascotEl.addEventListener("pointerdown", (e) => {
      mascotPointerStart = { x: e.clientX, y: e.clientY };
    });
    this.mascotEl.addEventListener("pointerup", (e) => {
      const dx = Math.abs(e.clientX - mascotPointerStart.x);
      const dy = Math.abs(e.clientY - mascotPointerStart.y);
      if (dx < 5 && dy < 5 && this.fsmState === "idle") {
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

      document.addEventListener("pointermove", onPointerMove);
      document.addEventListener("pointerup", onPointerUp);
    };

    const onPointerMove = (e: PointerEvent) => {
      if (e.pointerId !== pointerId) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      if (!this.isDragging && Math.abs(dx) < 6 && Math.abs(dy) < 6) return;

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
    if (!text || this.fsmState !== "idle") return;

    this.messages.push({ id: `msg-${Date.now()}`, role: "user", content: text, timestamp: Date.now() });
    input.value = "";
    btn.disabled = true;
    btn.classList.remove("active");

    this.transition("SEND", text);
  }

  // ── Mascot Visual (purely cosmetic, driven by FSM) ──

  private _setMascotVisual(state: MascotState) {
    if (this.mascotVisual === state) return;
    this.mascotVisual = state;
    this.animator?.setState(state);
  }

  // ── Speech Bubble ──

  private setSpeechText(text: string, animate = true, markdown = false) {
    if (!this.speechTextEl) return;
    const apply = () => {
      if (markdown) {
        this.speechTextEl.innerHTML = renderMarkdown(text);
      } else {
        this.speechTextEl.textContent = text;
      }
      this.speechTextEl.style.opacity = "1";
    };
    if (animate) {
      this.speechTextEl.style.opacity = "0";
      setTimeout(apply, 200);
    } else {
      apply();
    }
  }

  private startPhraseRotation() {
    this.stopPhraseRotation();
    this.phraseTimer = setInterval(() => {
      if (this.fsmState !== "idle") return;
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
