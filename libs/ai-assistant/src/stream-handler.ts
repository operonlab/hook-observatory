/**
 * SSE stream handler for AI assistant chat.
 * Connects to backend, receives StreamBlock events, and invokes callbacks.
 */

import type { StreamBlock } from "./types";

const MAX_RETRIES = 3;
const BASE_RETRY_MS = 1000;

export interface StreamCallbacks {
  onContent: (text: string, isDelta: boolean) => void;
  onThinking: () => void;
  onError: (message: string) => void;
  onDone: () => void;
}

export function startStream(
  apiUrl: string,
  body: Record<string, unknown>,
  callbacks: StreamCallbacks,
): AbortController {
  const controller = new AbortController();
  let retryCount = 0;

  async function connect() {
    try {
      const response = await fetch(apiUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        credentials: "include",
        signal: controller.signal,
      });

      if (!response.ok) {
        callbacks.onError(`伺服器錯誤 (${response.status})`);
        callbacks.onDone();
        return;
      }

      const reader = response.body?.getReader();
      if (!reader) {
        callbacks.onError("無法讀取串流回應");
        callbacks.onDone();
        return;
      }

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        let currentEvent = "";

        for (const line of lines) {
          if (line.startsWith("event: ")) {
            currentEvent = line.slice(7).trim();
          } else if (line.startsWith("data: ") && currentEvent) {
            try {
              const block: StreamBlock = JSON.parse(line.slice(6));
              handleBlock(block, currentEvent, callbacks);
            } catch {
              // malformed JSON — skip
            }
            currentEvent = "";
          }
        }
      }

      // Stream ended normally — ensure done is called
      callbacks.onDone();
    } catch (err) {
      if (controller.signal.aborted) {
        callbacks.onDone(); // ensure state resets even on abort
        return;
      }

      if (retryCount < MAX_RETRIES) {
        const delay = BASE_RETRY_MS * 2 ** retryCount;
        retryCount++;
        setTimeout(connect, delay);
      } else {
        callbacks.onError("連線中斷");
        callbacks.onDone();
      }
    }
  }

  connect();
  return controller;
}

function handleBlock(
  block: StreamBlock,
  eventType: string,
  callbacks: StreamCallbacks,
) {
  switch (eventType) {
    case "thinking":
      callbacks.onThinking();
      break;
    case "content": {
      const text =
        typeof block.data.text === "string" ? block.data.text : "";
      const isDelta = block.data.is_delta !== false;
      callbacks.onContent(text, isDelta);
      break;
    }
    case "error": {
      const msg =
        typeof block.data.message === "string"
          ? block.data.message
          : "發生錯誤";
      callbacks.onError(msg);
      break;
    }
    case "done":
      // handled by stream end
      break;
  }
}
