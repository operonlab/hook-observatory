// Package codex implements TranscriptParser for Codex CLI JSONL transcripts.
package codex

import (
	"bytes"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/joneshong/agent-vista/internal/protocol"
)

// Parser implements parser.TranscriptParser for Codex CLI JSONL transcripts.
// Codex CLI writes one JSON object per line, appending incrementally.
type Parser struct {
	meta        protocol.SessionMeta
	lineBuf     []byte // buffered incomplete line from previous read
	initialized bool
}

// New creates a new Codex JSONL parser.
func New() *Parser {
	return &Parser{}
}

// Detect returns true if the file path looks like a Codex CLI transcript.
// Matches paths containing ".codex" or "/codex/" that end with ".jsonl".
func (p *Parser) Detect(path string) bool {
	if !strings.HasSuffix(path, ".jsonl") {
		return false
	}
	return strings.Contains(path, ".codex") || strings.Contains(path, "/codex/")
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
			// No complete line -- buffer the remainder
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
			// Skip malformed lines -- transcript may have partial writes
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

// record is the top-level JSONL line. All detail lives inside Payload.
type record struct {
	Type      string          `json:"type"`
	Timestamp string          `json:"timestamp"`
	Payload   json.RawMessage `json:"payload"`
}

// sessionMetaPayload is the payload of a "session_meta" record.
type sessionMetaPayload struct {
	ID            string `json:"id"`
	CWD           string `json:"cwd"`
	CLIVersion    string `json:"cli_version"`
	ModelProvider string `json:"model_provider"`
	Source        string `json:"source"`
	Originator    string `json:"originator"`
}

// itemPayload is the payload of a "response_item" record.
type itemPayload struct {
	Type      string          `json:"type"` // message, function_call, function_call_output
	Name      string          `json:"name"`
	Arguments string          `json:"arguments"`
	CallID    string          `json:"call_id"`
	Output    string          `json:"output"`
	ExitCode  *int            `json:"exit_code"`
	Role      string          `json:"role"`
	Content   json.RawMessage `json:"content"`
}

// eventPayload is the payload of an "event_msg" record.
type eventPayload struct {
	Type             string     `json:"type"` // task_started, token_count, task_complete, agent_reasoning, agent_message, user_message
	TurnID           string     `json:"turn_id"`
	Info             *tokenInfo `json:"info"`
	LastAgentMessage string     `json:"last_agent_message"`
	Text             string     `json:"text"`
	Message          string     `json:"message"`
}

// tokenInfo wraps the nested token usage inside event_msg/token_count.
type tokenInfo struct {
	TotalTokenUsage *totalTokenUsage `json:"total_token_usage"`
}

type totalTokenUsage struct {
	InputTokens  int `json:"input_tokens"`
	OutputTokens int `json:"output_tokens"`
	TotalTokens  int `json:"total_tokens"`
	CachedTokens int `json:"cached_input_tokens"`
}

// parseLine parses a single JSONL line into zero or more AgentEvents.
func (p *Parser) parseLine(line []byte) ([]protocol.AgentEvent, error) {
	var rec record
	if err := json.Unmarshal(line, &rec); err != nil {
		return nil, fmt.Errorf("invalid JSON: %w", err)
	}

	ts := parseTimestamp(rec.Timestamp)
	sid := p.meta.SessionID

	switch rec.Type {
	case "session_meta":
		return p.parseSessionMeta(rec, ts)
	case "response_item":
		return p.parseResponseItem(rec, ts, sid)
	case "event_msg":
		return p.parseEventMsg(rec, ts, sid)
	default:
		return nil, nil
	}
}

func (p *Parser) parseSessionMeta(rec record, ts time.Time) ([]protocol.AgentEvent, error) {
	var meta sessionMetaPayload
	if err := json.Unmarshal(rec.Payload, &meta); err != nil {
		return nil, fmt.Errorf("invalid session_meta payload: %w", err)
	}

	sid := meta.ID
	if sid == "" {
		return nil, nil
	}

	p.meta = protocol.SessionMeta{
		SessionID:  sid,
		CLIType:    protocol.CLICodex,
		ProjectDir: meta.CWD,
		StartTime:  ts,
	}
	p.initialized = true

	return []protocol.AgentEvent{{
		CLIType:   protocol.CLICodex,
		SessionID: sid,
		AgentID:   agentID(sid),
		Timestamp: ts,
		EventType: protocol.EventSessionStart,
		Metadata: map[string]any{
			"cwd":      meta.CWD,
			"version":  meta.CLIVersion,
			"provider": meta.ModelProvider,
			"source":   meta.Source,
		},
	}}, nil
}

func (p *Parser) parseResponseItem(rec record, ts time.Time, sid string) ([]protocol.AgentEvent, error) {
	if len(rec.Payload) == 0 {
		return nil, nil
	}

	var item itemPayload
	if err := json.Unmarshal(rec.Payload, &item); err != nil {
		return nil, fmt.Errorf("invalid response_item payload: %w", err)
	}

	switch item.Type {
	case "function_call":
		toolInput := protocol.TruncateToolInput(item.Arguments, 200)
		return []protocol.AgentEvent{{
			CLIType:    protocol.CLICodex,
			SessionID:  sid,
			AgentID:    agentID(sid),
			Timestamp:  ts,
			EventType:  protocol.EventToolStart,
			ToolName:   item.Name,
			ToolInput:  toolInput,
			ToolStatus: protocol.ToolRunning,
			Metadata:   map[string]any{"call_id": item.CallID},
		}}, nil

	case "function_call_output":
		status := protocol.ToolSuccess
		if item.ExitCode != nil && *item.ExitCode != 0 {
			status = protocol.ToolError
		}
		return []protocol.AgentEvent{{
			CLIType:    protocol.CLICodex,
			SessionID:  sid,
			AgentID:    agentID(sid),
			Timestamp:  ts,
			EventType:  protocol.EventToolDone,
			ToolStatus: status,
			Metadata:   map[string]any{"call_id": item.CallID},
		}}, nil
	}

	return nil, nil
}

func (p *Parser) parseEventMsg(rec record, ts time.Time, sid string) ([]protocol.AgentEvent, error) {
	var evt eventPayload
	if err := json.Unmarshal(rec.Payload, &evt); err != nil {
		return nil, fmt.Errorf("invalid event_msg payload: %w", err)
	}

	switch evt.Type {
	case "token_count":
		var tokens *protocol.TokenUsage
		if evt.Info != nil && evt.Info.TotalTokenUsage != nil {
			u := evt.Info.TotalTokenUsage
			tokens = &protocol.TokenUsage{
				Input:  u.InputTokens,
				Output: u.OutputTokens,
				Cached: u.CachedTokens,
				Total:  u.TotalTokens,
			}
		}
		return []protocol.AgentEvent{{
			CLIType:   protocol.CLICodex,
			SessionID: sid,
			AgentID:   agentID(sid),
			Timestamp: ts,
			EventType: protocol.EventIdle,
			Tokens:    tokens,
		}}, nil

	case "task_complete":
		return []protocol.AgentEvent{{
			CLIType:   protocol.CLICodex,
			SessionID: sid,
			AgentID:   agentID(sid),
			Timestamp: ts,
			EventType: protocol.EventSessionEnd,
			Metadata:  map[string]any{"summary": evt.LastAgentMessage},
		}}, nil

	case "agent_reasoning":
		if evt.Text != "" {
			return []protocol.AgentEvent{{
				CLIType:   protocol.CLICodex,
				SessionID: sid,
				AgentID:   agentID(sid),
				Timestamp: ts,
				EventType: protocol.EventThinking,
				Metadata:  map[string]any{"text": protocol.TruncateToolInput(evt.Text, 200)},
			}}, nil
		}

	case "agent_message":
		if evt.Message != "" {
			return []protocol.AgentEvent{{
				CLIType:   protocol.CLICodex,
				SessionID: sid,
				AgentID:   agentID(sid),
				Timestamp: ts,
				EventType: protocol.EventMessage,
				Metadata:  map[string]any{"text": protocol.TruncateToolInput(evt.Message, 200)},
			}}, nil
		}
	}

	return nil, nil
}

// --- Helpers ---

func agentID(sessionID string) string {
	return "codex-" + sessionID
}

func parseTimestamp(s string) time.Time {
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
