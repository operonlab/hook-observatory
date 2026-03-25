export type MascotState = "idle" | "thinking" | "speaking" | "wave";
export type AssistantMode = "workshop" | "blog";
export type ThemeMode = "auto" | "light" | "dark";
export type Position = "bottom-right" | "bottom-left";

export interface StreamBlock {
  id: string;
  type: "thinking" | "content" | "source" | "progress" | "error" | "done";
  data: Record<string, unknown>;
  timestamp: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: number;
}
