// Mirrors internal/protocol/event.go
// FROZEN: Both worktrees depend on these types. Modify only on main branch.

export type CLIType = "claude" | "codex" | "gemini";

export type AgentEventType =
  | "tool_start"
  | "tool_done"
  | "tool_permission"
  | "message"
  | "thinking"
  | "idle"
  | "waiting"
  | "session_start"
  | "session_end"
  | "sub_agent_start"
  | "sub_agent_end"
  | "process_resting";

export type ToolStatus = "running" | "success" | "error";

export interface TokenUsage {
  input: number;
  output: number;
  cached?: number;
  total: number;
}

export interface AgentEvent {
  cli_type: CLIType;
  session_id: string;
  agent_id: string;
  timestamp: string; // ISO 8601
  event_type: AgentEventType;
  tool_name?: string;
  tool_input?: string; // truncated to 200 chars
  tool_status?: ToolStatus;
  tokens?: TokenUsage;
  sub_agent?: boolean;
  parent_id?: string;
  metadata?: Record<string, unknown>;
}
