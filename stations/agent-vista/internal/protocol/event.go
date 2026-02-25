// Package protocol defines shared data models for Agent Vista.
// FROZEN: Both worktrees depend on these types. Modify only on main branch.
package protocol

import "time"

// CLIType identifies which LLM CLI produced the event.
type CLIType string

const (
	CLIClaude CLIType = "claude"
	CLICodex  CLIType = "codex"
	CLIGemini CLIType = "gemini"
)

// AgentEventType categorizes the kind of event.
type AgentEventType string

const (
	EventToolStart     AgentEventType = "tool_start"
	EventToolDone      AgentEventType = "tool_done"
	EventToolPermission AgentEventType = "tool_permission"
	EventMessage       AgentEventType = "message"
	EventThinking      AgentEventType = "thinking"
	EventIdle          AgentEventType = "idle"
	EventWaiting       AgentEventType = "waiting"
	EventSessionStart  AgentEventType = "session_start"
	EventSessionEnd    AgentEventType = "session_end"
	EventSubAgentStart  AgentEventType = "sub_agent_start"
	EventSubAgentEnd    AgentEventType = "sub_agent_end"
	EventProcessResting AgentEventType = "process_resting"
)

// ToolStatus represents the outcome of a tool invocation.
type ToolStatus string

const (
	ToolRunning ToolStatus = "running"
	ToolSuccess ToolStatus = "success"
	ToolError   ToolStatus = "error"
)

// TokenUsage tracks token consumption for a single event.
type TokenUsage struct {
	Input  int `json:"input"`
	Output int `json:"output"`
	Cached int `json:"cached,omitempty"`
	Total  int `json:"total"`
}

// AgentEvent is the unified event model produced by all three CLI parsers.
type AgentEvent struct {
	CLIType    CLIType        `json:"cli_type"`
	SessionID  string         `json:"session_id"`
	AgentID    string         `json:"agent_id"`
	Timestamp  time.Time      `json:"timestamp"`
	EventType  AgentEventType `json:"event_type"`
	ToolName   string         `json:"tool_name,omitempty"`
	ToolInput  string         `json:"tool_input,omitempty"`  // truncated to 200 chars
	ToolStatus ToolStatus     `json:"tool_status,omitempty"`
	Tokens     *TokenUsage    `json:"tokens,omitempty"`
	SubAgent   bool           `json:"sub_agent,omitempty"`
	ParentID   string         `json:"parent_id,omitempty"`
	Metadata   map[string]any `json:"metadata,omitempty"`
}

// TruncateToolInput ensures tool_input doesn't exceed maxLen characters.
func TruncateToolInput(s string, maxLen int) string {
	if len(s) <= maxLen {
		return s
	}
	return s[:maxLen] + "..."
}
