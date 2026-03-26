/**
 * SSE chat client for the desktop assistant.
 * Adapted from libs/ai-assistant/src/stream-handler.ts with Bearer token auth
 * and configurable API URL.
 */

export interface StreamCallbacks {
  onContent: (text: string, isDelta: boolean) => void;
  onThinking: () => void;
  onError: (message: string) => void;
  onDone: () => void;
}

export interface ChatClientConfig {
  apiUrl: string;
  apiKey: string;
}

interface StreamBlock {
  id: string;
  type: "thinking" | "content" | "source" | "progress" | "error" | "done";
  data: Record<string, unknown>;
  timestamp: string;
}

const MAX_RETRIES = 3;
const BASE_RETRY_MS = 1000;

/**
 * Start a streaming chat request.
 *
 * @param config  API endpoint and Bearer token.
 * @param body    Request payload (message, history, etc.).
 * @param cbs     Stream event callbacks.
 * @returns AbortController — call controller.abort() to cancel.
 */
export function startChatStream(
  config: ChatClientConfig,
  body: Record<string, unknown>,
  cbs: StreamCallbacks,
): AbortController {
  const controller = new AbortController();
  let retryCount = 0;

  async function connect(): Promise<void> {
    try {
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };

      // Bearer token: included only when an API key is set.
      if (config.apiKey.trim()) {
        headers["Authorization"] = `Bearer ${config.apiKey.trim()}`;
      }

      const response = await fetch(config.apiUrl, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
        signal: controller.signal,
        // No credentials: "include" — desktop app sends explicit Bearer token.
      });

      if (!response.ok) {
        const status = response.status;
        if (status === 401) {
          cbs.onError("Unauthorized — check your API key in Settings.");
        } else if (status === 429) {
          cbs.onError("Rate limited — please wait a moment.");
        } else {
          cbs.onError(`Server error (${status})`);
        }
        cbs.onDone();
        return;
      }

      const reader = response.body?.getReader();
      if (!reader) {
        cbs.onError("Failed to read stream response.");
        cbs.onDone();
        return;
      }

      const decoder = new TextDecoder();
      let buffer = "";
      // currentEvent persists across chunk boundaries — event: and data: lines
      // may arrive in separate reads.
      let currentEvent = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (line.startsWith("event: ")) {
            currentEvent = line.slice(7).trim();
          } else if (line.startsWith("data: ") && currentEvent) {
            try {
              const block: StreamBlock = JSON.parse(line.slice(6));
              handleBlock(block, currentEvent, cbs);
            } catch {
              // Malformed JSON — skip silently.
            }
            currentEvent = "";
          }
          // id: and blank lines are ignored.
        }
      }

      // Stream ended normally.
      cbs.onDone();
    } catch (err) {
      if (controller.signal.aborted) return;

      if (retryCount < MAX_RETRIES) {
        // Exponential backoff with full jitter.
        const base = BASE_RETRY_MS * 2 ** retryCount;
        const jitter = Math.random() * base;
        retryCount++;
        setTimeout(connect, base + jitter);
      } else {
        cbs.onError("Connection lost — please retry.");
        cbs.onDone();
      }
    }
  }

  connect();
  return controller;
}

function handleBlock(
  block: StreamBlock,
  eventType: string,
  cbs: StreamCallbacks,
): void {
  switch (eventType) {
    case "thinking":
      cbs.onThinking();
      break;
    case "content": {
      const text =
        typeof block.data.text === "string" ? block.data.text : "";
      const isDelta = block.data.is_delta !== false;
      cbs.onContent(text, isDelta);
      break;
    }
    case "error": {
      const msg =
        typeof block.data.message === "string"
          ? block.data.message
          : "An error occurred.";
      cbs.onError(msg);
      break;
    }
    case "done":
      // done is handled by stream end (reader.read() returning done=true).
      break;
    default:
      // source, progress — ignored for now.
      break;
  }
}
