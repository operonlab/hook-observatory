// Mirrors internal/protocol/session.go
// FROZEN: Both worktrees depend on these types. Modify only on main branch.

import type { CLIType } from "./event";

export type AnimationState =
  | "IDLE"
  | "WALK"
  | "TYPE"
  | "THINK"
  | "WAIT"
  | "ERROR";

export type AgentStatus =
  | "active"
  | "thinking"
  | "typing"
  | "reading"
  | "waiting"
  | "idle"
  | "resting"
  | "offline"
  | "error";

export interface Position {
  x: number;
  y: number;
}

export interface AgentState {
  id: string;
  cli_type: CLIType;
  session_id: string;
  display_name: string;
  status: AgentStatus;
  current_tool?: string;
  tool_detail?: string;
  tokens_total: number;
  last_active: number; // unix ms
  position: Position;
  animation: AnimationState;
  sub_agents: AgentState[];
}
