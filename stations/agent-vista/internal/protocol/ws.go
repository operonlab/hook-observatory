package protocol

// WebSocket message types exchanged between server and client.
// FROZEN: Both worktrees depend on these types. Modify only on main branch.

// --- Server → Client Messages ---

// WSMessageType identifies the type of WebSocket message.
type WSMessageType string

const (
	WSTypeInit             WSMessageType = "init"
	WSTypeEvent            WSMessageType = "event"
	WSTypeAgentOnline      WSMessageType = "agent_online"
	WSTypeAgentOffline     WSMessageType = "agent_offline"
	WSTypeResourceSnapshot WSMessageType = "resource_snapshot"
)

// WSMessage is the envelope for all server→client WebSocket messages.
type WSMessage struct {
	Type WSMessageType `json:"type"`
	// Exactly one of the following will be non-nil, depending on Type.
	Init             *WSInit             `json:"init,omitempty"`
	Event            *AgentEvent         `json:"event,omitempty"`
	AgentOnline      *AgentState         `json:"agent_online,omitempty"`
	AgentOfflineID   string              `json:"agent_offline_id,omitempty"`
	ResourceSnapshot *WSResourceSnapshot `json:"resource_snapshot,omitempty"`
}

// WSInit is sent once on connection, containing all active agents.
type WSInit struct {
	Agents []AgentState `json:"agents"`
}

// ProcessInfo represents resource usage of a single LLM CLI process.
type ProcessInfo struct {
	PID     int32   `json:"pid"`
	Name    string  `json:"name"`
	CLIType CLIType `json:"cli_type,omitempty"`
	CPU     float64 `json:"cpu"`     // percentage
	RSS     uint64  `json:"rss"`     // bytes
	Threads int32   `json:"threads"`
	CWD     string  `json:"cwd,omitempty"` // working directory of root process
}

// WSResourceSnapshot is sent every 5 seconds with process resource data.
type WSResourceSnapshot struct {
	Processes []ProcessInfo `json:"processes"`
}

// --- Client → Server Messages ---

// WSClientMessageType identifies client-originated messages.
type WSClientMessageType string

const (
	WSCSaveLayout WSClientMessageType = "save_layout"
	WSCRescan     WSClientMessageType = "rescan"
)

// WSClientMessage is the envelope for client→server messages.
type WSClientMessage struct {
	Type   WSClientMessageType `json:"type"`
	Layout *OfficeLayout       `json:"layout,omitempty"`
}

// OfficeLayout defines the persistent layout configuration.
type OfficeLayout struct {
	Version      int      `json:"version"`
	Offices      []Office `json:"offices"`
	ActiveOffice string   `json:"active_office"`
}

// Office represents a single virtual office room.
type Office struct {
	ID         string      `json:"id"`
	Name       string      `json:"name"`
	Background string      `json:"background,omitempty"`
	Width      int         `json:"width"`  // tiles
	Height     int         `json:"height"` // tiles
	Furniture  []Furniture `json:"furniture"`
	AgentSeats []AgentSeat `json:"agent_seats"`
}

// Furniture is a decorative or functional item in the office.
type Furniture struct {
	ID       string `json:"id"`
	Type     string `json:"type"` // "desk", "chair", "plant", "monitor", etc.
	TileX    int    `json:"tile_x"`
	TileY    int    `json:"tile_y"`
	Width    int    `json:"width,omitempty"`    // tiles, default 1
	Height   int    `json:"height,omitempty"`   // tiles, default 1
	Rotation int    `json:"rotation,omitempty"` // degrees: 0, 90, 180, 270
}

// AgentSeat binds an agent to a position in the office.
type AgentSeat struct {
	AgentID   string `json:"agent_id"`
	TileX     int    `json:"tile_x"`
	TileY     int    `json:"tile_y"`
	Direction string `json:"direction"` // "up", "down", "left", "right"
	// Optional free-positioning mode (percentage-based, LazyOffice style)
	FreePosition *FreePosition `json:"free_position,omitempty"`
}

// FreePosition allows percentage-based positioning (LazyOffice pattern).
type FreePosition struct {
	LeftPct float64 `json:"left_pct"`
	TopPct  float64 `json:"top_pct"`
	Scale   float64 `json:"scale"`
	ZIndex  int     `json:"z_index"`
}
