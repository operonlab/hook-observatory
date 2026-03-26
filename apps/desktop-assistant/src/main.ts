/**
 * Desktop Assistant — main entry point.
 *
 * Responsibilities:
 *   - Load/persist settings (API URL + key) via localStorage.
 *   - Wire up chat input → SSE stream → speech bubble.
 *   - Track mouse position for future Live2D eye tracking.
 *   - Expose drag handle via Tauri invoke("start_drag").
 */

import { invoke } from "@tauri-apps/api/core";
import { startChatStream } from "./chat-client.ts";

// TODO: Uncomment when @workshop/live2d-core is published.
// import { Live2DRenderer } from "@workshop/live2d-core";

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

interface AssistantSettings {
  apiUrl: string;
  apiKey: string;
}

const DEFAULT_SETTINGS: AssistantSettings = {
  apiUrl: "https://workshop.joneshong.com/api/assistant/chat",
  apiKey: "",
};

const SETTINGS_KEY = "desktop-assistant:settings";

function loadSettings(): AssistantSettings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (raw) {
      return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) };
    }
  } catch {
    // Ignore parse errors — fall back to defaults.
  }
  return { ...DEFAULT_SETTINGS };
}

function saveSettings(settings: AssistantSettings): void {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

// ---------------------------------------------------------------------------
// DOM References
// ---------------------------------------------------------------------------

const chatInput = document.getElementById("chat-input") as HTMLInputElement;
const sendBtn = document.getElementById("send-btn") as HTMLButtonElement;
const speechBubble = document.getElementById("speech-bubble") as HTMLDivElement;
const bubbleText = document.getElementById("bubble-text") as HTMLDivElement;
const bubbleCursor = document.getElementById("bubble-cursor") as HTMLDivElement;
const dragHandle = document.getElementById("drag-handle") as HTMLDivElement;
const settingsBtn = document.getElementById("settings-btn") as HTMLButtonElement;
const settingsPanel = document.getElementById("settings-panel") as HTMLDivElement;
const apiUrlInput = document.getElementById("api-url-input") as HTMLInputElement;
const apiKeyInput = document.getElementById("api-key-input") as HTMLInputElement;
const settingsSaveBtn = document.getElementById("settings-save-btn") as HTMLButtonElement;
const settingsCloseBtn = document.getElementById("settings-close-btn") as HTMLButtonElement;

// ---------------------------------------------------------------------------
// Live2D (placeholder until @workshop/live2d-core is ready)
// ---------------------------------------------------------------------------

// TODO: Replace this stub with the real renderer when live2d-core is ready.
const renderer = {
  setMousePosition(_x: number, _y: number): void {
    // Will forward to Live2DRenderer.setMousePosition(x, y).
  },
  setState(_state: "idle" | "thinking" | "speaking" | "wave"): void {
    // Will update mascot expression and motion.
  },
};

// ---------------------------------------------------------------------------
// Mouse Tracking → renderer eye follow
// ---------------------------------------------------------------------------

document.addEventListener("mousemove", (e: MouseEvent) => {
  // Normalize to [-1, 1] relative to window center.
  const x = (e.clientX / window.innerWidth) * 2 - 1;
  const y = (e.clientY / window.innerHeight) * 2 - 1;
  renderer.setMousePosition(x, y);
});

// ---------------------------------------------------------------------------
// Window Drag via Tauri
// ---------------------------------------------------------------------------

dragHandle.addEventListener("mousedown", () => {
  invoke("start_drag").catch(console.error);
});

// ---------------------------------------------------------------------------
// Chat Logic
// ---------------------------------------------------------------------------

let settings = loadSettings();
let currentStream: AbortController | null = null;
let accumulatedText = "";

function showBubble(text: string): void {
  bubbleText.textContent = text;
  speechBubble.classList.remove("hidden");
}

function hideBubble(): void {
  speechBubble.classList.add("hidden");
}

function setStreaming(active: boolean): void {
  sendBtn.disabled = active;
  chatInput.disabled = active;
  if (active) {
    bubbleCursor.classList.remove("done");
    renderer.setState("thinking");
  } else {
    bubbleCursor.classList.add("done");
    renderer.setState("idle");
  }
}

async function sendMessage(): Promise<void> {
  const text = chatInput.value.trim();
  if (!text) return;

  chatInput.value = "";
  accumulatedText = "";
  showBubble("...");
  setStreaming(true);

  // Cancel any in-flight request.
  currentStream?.abort();

  currentStream = startChatStream(
    { apiUrl: settings.apiUrl, apiKey: settings.apiKey },
    { message: text },
    {
      onThinking: () => {
        renderer.setState("thinking");
        bubbleText.textContent = "...";
      },
      onContent: (chunk: string, isDelta: boolean) => {
        renderer.setState("speaking");
        if (isDelta) {
          accumulatedText += chunk;
        } else {
          accumulatedText = chunk;
        }
        bubbleText.textContent = accumulatedText;
        speechBubble.scrollTop = speechBubble.scrollHeight;
      },
      onError: (msg: string) => {
        bubbleText.textContent = `Error: ${msg}`;
        renderer.setState("idle");
      },
      onDone: () => {
        setStreaming(false);
        currentStream = null;
        // Auto-hide bubble after 30 seconds of inactivity.
        setTimeout(() => {
          if (!currentStream) hideBubble();
        }, 30_000);
      },
    },
  );
}

sendBtn.addEventListener("click", () => void sendMessage());

chatInput.addEventListener("keydown", (e: KeyboardEvent) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    void sendMessage();
  }
});

// ---------------------------------------------------------------------------
// Settings Panel
// ---------------------------------------------------------------------------

function openSettings(): void {
  apiUrlInput.value = settings.apiUrl;
  apiKeyInput.value = settings.apiKey;
  settingsPanel.classList.remove("hidden");
}

function closeSettings(): void {
  settingsPanel.classList.add("hidden");
}

settingsBtn.addEventListener("click", openSettings);
settingsCloseBtn.addEventListener("click", closeSettings);

settingsSaveBtn.addEventListener("click", () => {
  settings = {
    apiUrl: apiUrlInput.value.trim() || DEFAULT_SETTINGS.apiUrl,
    apiKey: apiKeyInput.value.trim(),
  };
  saveSettings(settings);
  closeSettings();
});

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

// Focus input on startup so the user can type immediately.
chatInput.focus();
