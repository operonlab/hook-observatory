// Package claude implements TranscriptParser for Claude Code JSONL transcripts.
package claude

import (
	"bytes"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/joneshong/agent-vista/internal/protocol"
)

// Parser implements parser.TranscriptParser for Claude Code JSONL transcripts.
// Claude Code writes one JSON object per line, appending incrementally.
type Parser struct {
	meta        protocol.SessionMeta
	lineBuf     []byte // buffered incomplete line from previous read
	initialized bool
}

// New creates a new Claude JSONL parser.
func New() *Parser {
	return &Parser{}
}

// Detect returns true if the file path looks like a Claude Code transcript.
// Matches both real paths (~/.claude/projects/*/conversations/*.jsonl)
// and testdata paths (testdata/claude/sample.jsonl).
func (p *Parser) Detect(path string) bool {
	if !strings.HasSuffix(path, ".jsonl") {
		return false
	}
	return strings.Contains(path, "/.claude/") || strings.Contains(path, "/claude/")
}

// ParseIncremental processes newly appended bytes and returns parsed events.
// newBytes contains raw bytes appended to the JSONL file since last read.
func (p *Parser) ParseIncremental(newBytes []byte) ([]protocol.AgentEvent, error) {
	data := append(p.lineBuf, newBytes...)
	p.lineBuf = nil

	var events []protocol.AgentEvent

	for len(data) > 0 {
		idx := bytes.IndexByte(data, '\n')
		if idx == -1 {
			// No complete line — buffer the remainder
			p.lineBuf = make([]byte, len(data))
			copy(p.lineBuf, data)
			break
		}

		line := bytes.TrimSpace(data[:idx])
		data = data[idx+1:]

		if len(line) == 0 {
			continue
		}

		evts, err := p.parseLine(line)
		if err != nil {
			// Skip malformed lines — transcript may have partial writes
			continue
		}
		events = append(events, evts...)
	}

	return events, nil
}

// SessionInfo returns metadata about the current session being parsed.
func (p *Parser) SessionInfo() protocol.SessionMeta {
	return p.meta
}

// Reset clears internal state.
func (p *Parser) Reset() {
	p.meta = protocol.SessionMeta{}
	p.lineBuf = nil
	p.initialized = false
}

// --- Internal JSONL record types ---

type record struct {
	Type      string  `json:"type"`
	Subtype   string  `json:"subtype"`
	Timestamp string  `json:"timestamp"`
	UUID      string  `json:"uuid"`
	SessionID string  `json:"sessionId"`
	CWD       string  `json:"cwd"`
	Version   string  `json:"version"`
	GitBranch string  `json:"gitBranch"`
	Message   *apiMsg `json:"message"` // wraps the Anthropic API message

	// progress record data
	Data json.RawMessage `json:"data"`

	// turn_duration fields (system/turn_duration)
	DurationMs       int `json:"duration_ms"`
	InputTokens      int `json:"input_tokens"`
	OutputTokens     int `json:"output_tokens"`
	CacheReadTokens  int `json:"cache_read_tokens"`
	CacheWriteTokens int `json:"cache_write_tokens"`
}

// apiMsg wraps the Anthropic API message inside assistant/user records.
type apiMsg struct {
	Model      string          `json:"model"`
	Role       string          `json:"role"`
	Content    []contentBlock  `json:"content"`
	Usage      *apiUsage       `json:"usage"`
	StopReason string          `json:"stop_reason"`
}

type apiUsage struct {
	InputTokens  int `json:"input_tokens"`
	OutputTokens int `json:"output_tokens"`
	CacheRead    int `json:"cache_read_input_tokens"`
	CacheCreate  int `json:"cache_creation_input_tokens"`
}

type contentBlock struct {
	Type      string          `json:"type"` // text, tool_use, tool_result
	Text      string          `json:"text"`
	ID        string          `json:"id"`   // tool_use id
	Name      string          `json:"name"` // tool name
	Input     json.RawMessage `json:"input"`
	ToolUseID string          `json:"tool_use_id"` // tool_result ref
	Content   json.RawMessage `json:"content"`     // tool_result output (string or array)
	IsError   bool            `json:"is_error"`
}

// progressData is the data field of a progress record.
type progressData struct {
	Type            string `json:"type"`             // hook_progress, agent_progress, etc.
	AgentType       string `json:"agent_type"`       // agent_progress
	Status          string `json:"status"`           // running, done, error
	Description     string `json:"description"`
	ParentToolUseID string `json:"parent_tool_use_id"`
}

// parseLine parses a single JSONL line into zero or more AgentEvents.
func (p *Parser) parseLine(line []byte) ([]protocol.AgentEvent, error) {
	var rec record
	if err := json.Unmarshal(line, &rec); err != nil {
		return nil, fmt.Errorf("invalid JSON: %w", err)
	}

	ts := parseTimestamp(rec.Timestamp)
	sid := rec.SessionID
	if sid == "" {
		sid = p.meta.SessionID
	}

	// Auto-initialize from first record that has a sessionId
	if !p.initialized && sid != "" {
		p.meta = protocol.SessionMeta{
			SessionID:  sid,
			CLIType:    protocol.CLIClaude,
			ProjectDir: rec.CWD,
			StartTime:  ts,
		}
		p.initialized = true

		// Try to get model from assistant message
		model := ""
		if rec.Message != nil && rec.Message.Model != "" {
			model = rec.Message.Model
		}
		p.meta.Model = model

		return []protocol.AgentEvent{{
			CLIType:   protocol.CLIClaude,
			SessionID: sid,
			AgentID:   agentID(sid),
			Timestamp: ts,
			EventType: protocol.EventSessionStart,
			Metadata: map[string]any{
				"model":   model,
				"cwd":     rec.CWD,
				"version": rec.Version,
			},
		}}, nil
	}

	switch rec.Type {
	case "system":
		return p.parseSystem(rec, ts, sid)
	case "assistant":
		return p.parseAssistant(rec, ts, sid)
	case "user":
		return p.parseUser(rec, ts, sid)
	case "progress":
		return p.parseProgress(rec, ts, sid)
	default:
		return nil, nil
	}
}

func (p *Parser) parseSystem(rec record, ts time.Time, sid string) ([]protocol.AgentEvent, error) {
	switch rec.Subtype {
	case "turn_duration":
		tokens := &protocol.TokenUsage{
			Input:  rec.InputTokens,
			Output: rec.OutputTokens,
			Cached: rec.CacheReadTokens,
			Total:  rec.InputTokens + rec.OutputTokens,
		}
		return []protocol.AgentEvent{{
			CLIType:   protocol.CLIClaude,
			SessionID: sid,
			AgentID:   agentID(sid),
			Timestamp: ts,
			EventType: protocol.EventIdle,
			Tokens:    tokens,
		}}, nil
	}

	return nil, nil
}

func (p *Parser) parseAssistant(rec record, ts time.Time, sid string) ([]protocol.AgentEvent, error) {
	if rec.Message == nil {
		return nil, nil
	}

	// Update model if we didn't have it
	if p.meta.Model == "" && rec.Message.Model != "" {
		p.meta.Model = rec.Message.Model
	}

	var events []protocol.AgentEvent

	for _, c := range rec.Message.Content {
		switch c.Type {
		case "text":
			events = append(events, protocol.AgentEvent{
				CLIType:   protocol.CLIClaude,
				SessionID: sid,
				AgentID:   agentID(sid),
				Timestamp: ts,
				EventType: protocol.EventMessage,
				Metadata:  map[string]any{"text": protocol.TruncateToolInput(c.Text, 200)},
			})

		case "tool_use":
			toolInput := ""
			if len(c.Input) > 0 {
				toolInput = protocol.TruncateToolInput(string(c.Input), 200)
			}

			evt := protocol.AgentEvent{
				CLIType:    protocol.CLIClaude,
				SessionID:  sid,
				AgentID:    agentID(sid),
				Timestamp:  ts,
				EventType:  protocol.EventToolStart,
				ToolName:   c.Name,
				ToolInput:  toolInput,
				ToolStatus: protocol.ToolRunning,
				Metadata:   map[string]any{"tool_use_id": c.ID},
			}

			// Task tool invocations spawn sub-agents
			if c.Name == "Task" {
				evt.EventType = protocol.EventSubAgentStart
				evt.SubAgent = true
			}

			events = append(events, evt)
		}
	}

	return events, nil
}

func (p *Parser) parseUser(rec record, ts time.Time, sid string) ([]protocol.AgentEvent, error) {
	if rec.Message == nil {
		return nil, nil
	}

	var events []protocol.AgentEvent

	for _, c := range rec.Message.Content {
		if c.Type != "tool_result" {
			continue
		}

		status := protocol.ToolSuccess
		if c.IsError {
			status = protocol.ToolError
		}

		events = append(events, protocol.AgentEvent{
			CLIType:    protocol.CLIClaude,
			SessionID:  sid,
			AgentID:    agentID(sid),
			Timestamp:  ts,
			EventType:  protocol.EventToolDone,
			ToolStatus: status,
			Metadata:   map[string]any{"tool_use_id": c.ToolUseID},
		})
	}

	return events, nil
}

func (p *Parser) parseProgress(rec record, ts time.Time, sid string) ([]protocol.AgentEvent, error) {
	if len(rec.Data) == 0 {
		return nil, nil
	}

	var pd progressData
	if err := json.Unmarshal(rec.Data, &pd); err != nil {
		return nil, nil
	}

	// Only handle agent_progress type
	if pd.Type != "agent_progress" {
		return nil, nil
	}

	eventType := protocol.EventSubAgentStart
	if pd.Status == "done" || pd.Status == "error" {
		eventType = protocol.EventSubAgentEnd
	}

	return []protocol.AgentEvent{{
		CLIType:   protocol.CLIClaude,
		SessionID: sid,
		AgentID:   agentID(sid),
		Timestamp: ts,
		EventType: eventType,
		SubAgent:  true,
		Metadata: map[string]any{
			"agent_type":         pd.AgentType,
			"status":             pd.Status,
			"description":        pd.Description,
			"parent_tool_use_id": pd.ParentToolUseID,
		},
	}}, nil
}

// --- Helpers ---

func agentID(sessionID string) string {
	return "claude-" + sessionID
}

func parseTimestamp(s string) time.Time {
	// Try RFC3339 variants
	for _, layout := range []string{
		time.RFC3339Nano,
		time.RFC3339,
		"2006-01-02T15:04:05.000Z",
	} {
		if t, err := time.Parse(layout, s); err == nil {
			return t
		}
	}
	return time.Now()
}
