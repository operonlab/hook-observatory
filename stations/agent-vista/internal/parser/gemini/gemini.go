// Package gemini implements TranscriptParser for Gemini CLI JSON transcripts.
package gemini

import (
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/joneshong/agent-vista/internal/protocol"
)

// Parser implements parser.TranscriptParser for Gemini CLI JSON transcripts.
// Gemini writes a single JSON file that gets overwritten on each update.
// The parser diffs against previous state to emit only new events.
type Parser struct {
	meta             protocol.SessionMeta
	lastMessageCount int
	lastUpdated      string
}

// New creates a new Gemini JSON parser.
func New() *Parser {
	return &Parser{}
}

// Detect returns true if the file path looks like a Gemini CLI transcript.
// Matches paths containing ".gemini" or "/gemini/" that end with ".json".
func (p *Parser) Detect(path string) bool {
	if !strings.HasSuffix(path, ".json") {
		return false
	}
	return strings.Contains(path, ".gemini") || strings.Contains(path, "/gemini/")
}

// ParseIncremental processes the full file content and returns new events
// by diffing against previous state. newBytes contains the complete JSON file.
func (p *Parser) ParseIncremental(newBytes []byte) ([]protocol.AgentEvent, error) {
	var doc transcript
	if err := json.Unmarshal(newBytes, &doc); err != nil {
		return nil, fmt.Errorf("gemini: invalid JSON: %w", err)
	}

	// If lastUpdated hasn't changed and we've already processed messages, no new events
	if p.lastUpdated == doc.LastUpdated && p.lastMessageCount == len(doc.Messages) {
		return nil, nil
	}

	var events []protocol.AgentEvent

	// On first call, emit session start
	if p.lastMessageCount == 0 {
		// Find model from first gemini message
		model := ""
		for _, m := range doc.Messages {
			if m.Type != "user" && m.Model != "" {
				model = m.Model
				break
			}
		}

		startTime := doc.StartTime
		if startTime == "" {
			startTime = doc.LastUpdated
		}

		p.meta = protocol.SessionMeta{
			SessionID: doc.SessionID,
			CLIType:   protocol.CLIGemini,
			StartTime: parseTimestamp(startTime),
			Model:     model,
		}

		events = append(events, protocol.AgentEvent{
			CLIType:   protocol.CLIGemini,
			SessionID: doc.SessionID,
			AgentID:   agentID(doc.SessionID),
			Timestamp: parseTimestamp(startTime),
			EventType: protocol.EventSessionStart,
			Metadata: map[string]any{
				"model": model,
			},
		})
	}

	// Process only new messages
	newMessages := doc.Messages[p.lastMessageCount:]
	for _, msg := range newMessages {
		msgEvents := p.parseMessage(doc.SessionID, msg)
		events = append(events, msgEvents...)
	}

	// Update state
	p.lastMessageCount = len(doc.Messages)
	p.lastUpdated = doc.LastUpdated

	return events, nil
}

// SessionInfo returns metadata about the current session being parsed.
func (p *Parser) SessionInfo() protocol.SessionMeta {
	return p.meta
}

// Reset clears internal state.
func (p *Parser) Reset() {
	p.meta = protocol.SessionMeta{}
	p.lastMessageCount = 0
	p.lastUpdated = ""
}

// --- Internal JSON types ---

type transcript struct {
	LastUpdated string    `json:"lastUpdated"`
	SessionID   string    `json:"sessionId"`
	StartTime   string    `json:"startTime"`
	Messages    []message `json:"messages"`
}

type message struct {
	Type      string          `json:"type"`
	Timestamp string          `json:"timestamp"`
	Content   json.RawMessage `json:"content"`   // string for gemini messages, array for user messages
	Thoughts  json.RawMessage `json:"thoughts"`  // array of {subject, description} objects
	ToolCalls []toolCall      `json:"toolCalls"`
	Tokens    *tokens         `json:"tokens"`
	Model     string          `json:"model"`
}

type toolCall struct {
	Name   string         `json:"name"`
	Args   map[string]any `json:"args"`
	Result string         `json:"result"`
}

// contentPart represents an element in the content array (user messages).
type contentPart struct {
	Text         string        `json:"text,omitempty"`
	FunctionCall *functionCall `json:"functionCall,omitempty"`
}

type functionCall struct {
	Name string         `json:"name"`
	Args map[string]any `json:"args"`
}

// thoughtPart represents one element in the thoughts array.
type thoughtPart struct {
	Subject     string `json:"subject"`
	Description string `json:"description"`
}

type tokens struct {
	Input    int `json:"input"`
	Output   int `json:"output"`
	Cached   int `json:"cached"`
	Thoughts int `json:"thoughts"`
	Tool     int `json:"tool"`
	Total    int `json:"total"`
}

// parseMessage converts a single Gemini message into AgentEvents.
func (p *Parser) parseMessage(sessionID string, msg message) []protocol.AgentEvent {
	if msg.Type == "user" {
		// User messages don't produce events
		return nil
	}

	var events []protocol.AgentEvent
	ts := parseTimestamp(msg.Timestamp)
	aid := agentID(sessionID)

	// 1. Thoughts field -> EventThinking (array of {subject, description})
	thoughtsText := extractThoughts(msg.Thoughts)
	if thoughtsText != "" {
		events = append(events, protocol.AgentEvent{
			CLIType:   protocol.CLIGemini,
			SessionID: sessionID,
			AgentID:   aid,
			Timestamp: ts,
			EventType: protocol.EventThinking,
			Metadata: map[string]any{
				"text": protocol.TruncateToolInput(thoughtsText, 200),
			},
		})
	}

	// 2. Each toolCall -> EventToolStart + EventToolDone pair
	for _, tc := range msg.ToolCalls {
		argsJSON, _ := json.Marshal(tc.Args)
		toolInput := protocol.TruncateToolInput(string(argsJSON), 200)

		// tool_start
		events = append(events, protocol.AgentEvent{
			CLIType:    protocol.CLIGemini,
			SessionID:  sessionID,
			AgentID:    aid,
			Timestamp:  ts,
			EventType:  protocol.EventToolStart,
			ToolName:   tc.Name,
			ToolInput:  toolInput,
			ToolStatus: protocol.ToolRunning,
		})

		// tool_done (Gemini records call + result together)
		status := protocol.ToolSuccess
		if strings.Contains(strings.ToLower(tc.Result), "error") {
			status = protocol.ToolError
		}

		events = append(events, protocol.AgentEvent{
			CLIType:    protocol.CLIGemini,
			SessionID:  sessionID,
			AgentID:    aid,
			Timestamp:  ts,
			EventType:  protocol.EventToolDone,
			ToolName:   tc.Name,
			ToolStatus: status,
		})
	}

	// 2b. Content-embedded function calls (some Gemini versions embed these in content array)
	funcCalls := extractFunctionCalls(msg.Content)
	for _, fc := range funcCalls {
		argsJSON, _ := json.Marshal(fc.Args)
		toolInput := protocol.TruncateToolInput(string(argsJSON), 200)

		events = append(events, protocol.AgentEvent{
			CLIType:    protocol.CLIGemini,
			SessionID:  sessionID,
			AgentID:    aid,
			Timestamp:  ts,
			EventType:  protocol.EventToolStart,
			ToolName:   fc.Name,
			ToolInput:  toolInput,
			ToolStatus: protocol.ToolRunning,
		})
		events = append(events, protocol.AgentEvent{
			CLIType:    protocol.CLIGemini,
			SessionID:  sessionID,
			AgentID:    aid,
			Timestamp:  ts,
			EventType:  protocol.EventToolDone,
			ToolName:   fc.Name,
			ToolStatus: protocol.ToolSuccess,
		})
	}

	// 3. Content field -> EventMessage
	contentText := extractContentText(msg.Content)
	if contentText != "" {
		events = append(events, protocol.AgentEvent{
			CLIType:   protocol.CLIGemini,
			SessionID: sessionID,
			AgentID:   aid,
			Timestamp: ts,
			EventType: protocol.EventMessage,
			Metadata: map[string]any{
				"text": protocol.TruncateToolInput(contentText, 200),
			},
		})
	}

	// 4. Tokens field -> EventIdle with token usage
	if msg.Tokens != nil {
		total := msg.Tokens.Total
		if total == 0 {
			total = msg.Tokens.Input + msg.Tokens.Output
		}
		events = append(events, protocol.AgentEvent{
			CLIType:   protocol.CLIGemini,
			SessionID: sessionID,
			AgentID:   aid,
			Timestamp: ts,
			EventType: protocol.EventIdle,
			Tokens: &protocol.TokenUsage{
				Input:  msg.Tokens.Input,
				Output: msg.Tokens.Output,
				Cached: msg.Tokens.Cached,
				Total:  total,
			},
		})
	}

	return events
}

// extractContentText extracts text from Content which can be either a JSON string or array of parts.
func extractContentText(raw json.RawMessage) string {
	if len(raw) == 0 {
		return ""
	}

	// Try as string first (gemini messages)
	var s string
	if err := json.Unmarshal(raw, &s); err == nil {
		return s
	}

	// Try as array of content parts (user messages or function call content)
	var parts []contentPart
	if err := json.Unmarshal(raw, &parts); err == nil {
		var texts []string
		for _, p := range parts {
			if p.Text != "" {
				texts = append(texts, p.Text)
			}
		}
		return strings.Join(texts, "\n")
	}

	return ""
}

// extractFunctionCalls extracts function calls from content array (if present).
func extractFunctionCalls(raw json.RawMessage) []functionCall {
	if len(raw) == 0 {
		return nil
	}

	var parts []contentPart
	if err := json.Unmarshal(raw, &parts); err != nil {
		return nil
	}

	var calls []functionCall
	for _, p := range parts {
		if p.FunctionCall != nil {
			calls = append(calls, *p.FunctionCall)
		}
	}
	return calls
}

// extractThoughts extracts text from the thoughts field (array of {subject, description}).
func extractThoughts(raw json.RawMessage) string {
	if len(raw) == 0 {
		return ""
	}

	// Try as string first (backward compat)
	var s string
	if err := json.Unmarshal(raw, &s); err == nil {
		return s
	}

	// Try as array of thought parts
	var parts []thoughtPart
	if err := json.Unmarshal(raw, &parts); err == nil {
		var texts []string
		for _, p := range parts {
			if p.Subject != "" {
				texts = append(texts, p.Subject)
			}
		}
		return strings.Join(texts, " → ")
	}

	return ""
}

// --- Helpers ---

func agentID(sessionID string) string {
	return "gemini-" + sessionID
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
