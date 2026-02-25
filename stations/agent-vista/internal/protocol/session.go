package protocol

import "time"

// AnimationState drives the pixel character's visual state.
type AnimationState string

const (
	AnimIdle  AnimationState = "IDLE"
	AnimWalk  AnimationState = "WALK"
	AnimType  AnimationState = "TYPE"
	AnimThink AnimationState = "THINK"
	AnimWait  AnimationState = "WAIT"
	AnimError AnimationState = "ERROR"
)

// AgentStatus represents the logical status of an agent.
type AgentStatus string

const (
	StatusActive   AgentStatus = "active"
	StatusThinking AgentStatus = "thinking"
	StatusTyping   AgentStatus = "typing"
	StatusReading  AgentStatus = "reading"
	StatusWaiting  AgentStatus = "waiting"
	StatusIdle     AgentStatus = "idle"
	StatusResting  AgentStatus = "resting"
	StatusOffline  AgentStatus = "offline"
	StatusError    AgentStatus = "error"
)

// SessionMeta holds metadata about a discovered transcript session.
type SessionMeta struct {
	SessionID  string    `json:"session_id"`
	CLIType    CLIType   `json:"cli_type"`
	ProjectDir string    `json:"project_dir,omitempty"`
	StartTime  time.Time `json:"start_time"`
	Model      string    `json:"model,omitempty"`
	FilePath   string    `json:"file_path"`
}

// Position represents a 2D coordinate in the office.
type Position struct {
	X int `json:"x"`
	Y int `json:"y"`
}

// AgentState is the full state of an agent as sent to the frontend.
type AgentState struct {
	ID          string         `json:"id"`
	CLIType     CLIType        `json:"cli_type"`
	SessionID   string         `json:"session_id"`
	DisplayName string         `json:"display_name"`
	Status      AgentStatus    `json:"status"`
	CurrentTool string         `json:"current_tool,omitempty"`
	ToolDetail  string         `json:"tool_detail,omitempty"`
	TokensTotal int            `json:"tokens_total"`
	LastActive  int64          `json:"last_active"` // unix ms
	Position    Position       `json:"position"`
	Animation   AnimationState `json:"animation"`
	SubAgents   []AgentState   `json:"sub_agents,omitempty"`
	ProjectDir  string         `json:"project_dir,omitempty"` // working directory for process correlation
}
