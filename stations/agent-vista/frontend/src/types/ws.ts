// Mirrors internal/protocol/ws.go
// FROZEN: Both worktrees depend on these types. Modify only on main branch.

import type { AgentEvent } from "./event";
import type { CLIType } from "./event";
import type { AgentState } from "./agent";

// --- Server → Client ---

export type WSMessageType =
  | "init"
  | "event"
  | "agent_online"
  | "agent_offline"
  | "resource_snapshot";

export interface ProcessInfo {
  pid: number;
  name: string;
  cli_type?: CLIType;
  cpu: number;
  rss: number; // bytes
  threads: number;
}

export interface WSMessage {
  type: WSMessageType;
  init?: { agents: AgentState[] };
  event?: AgentEvent;
  agent_online?: AgentState;
  agent_offline_id?: string;
  resource_snapshot?: { processes: ProcessInfo[] };
}

// --- Client → Server ---

export type WSClientMessageType = "save_layout" | "rescan";

export interface OfficeLayout {
  version: number;
  offices: Office[];
  active_office: string;
}

export interface Office {
  id: string;
  name: string;
  background?: string;
  width: number;
  height: number;
  furniture: Furniture[];
  agent_seats: AgentSeat[];
}

export interface Furniture {
  id: string;
  type: string;
  tile_x: number;
  tile_y: number;
  width?: number;
  height?: number;
}

export interface AgentSeat {
  agent_id: string;
  tile_x: number;
  tile_y: number;
  direction: "up" | "down" | "left" | "right";
  free_position?: {
    left_pct: number;
    top_pct: number;
    scale: number;
    z_index: number;
  };
}

export interface WSClientMessage {
  type: WSClientMessageType;
  layout?: OfficeLayout;
}
