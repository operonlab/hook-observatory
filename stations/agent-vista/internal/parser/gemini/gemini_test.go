package gemini

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"github.com/joneshong/agent-vista/internal/protocol"
)

func testdataPath(name string) string {
	return filepath.Join("..", "..", "..", "testdata", "gemini", name)
}

func TestDetect(t *testing.T) {
	p := New()

	cases := []struct {
		path string
		want bool
	}{
		{"~/.gemini/sessions/conversation.json", true},
		{"/Users/me/.gemini/output/transcript.json", true},
		{"/path/to/testdata/gemini/sample.json", true},
		{"/some/path/.gemini/file.jsonl", false},       // wrong extension
		{"/some/path/.claude/conversations/a.json", false}, // wrong CLI
		{"/some/path/.codex/sessions/file.json", false},    // wrong CLI
		{"random.txt", false},
		{"/path/gemini/transcript.json", true},  // contains /gemini/
		{"/path/.gemini/data.json", true},       // contains .gemini
	}

	for _, tc := range cases {
		if got := p.Detect(tc.path); got != tc.want {
			t.Errorf("Detect(%q) = %v, want %v", tc.path, got, tc.want)
		}
	}
}

func TestParseFullFile(t *testing.T) {
	data, err := os.ReadFile(testdataPath("sample.json"))
	if err != nil {
		t.Fatalf("failed to read test fixture: %v", err)
	}

	p := New()
	events, err := p.ParseIncremental(data)
	if err != nil {
		t.Fatalf("ParseIncremental error: %v", err)
	}

	if len(events) == 0 {
		t.Fatal("expected events, got none")
	}

	// Verify session metadata was captured
	meta := p.SessionInfo()
	if meta.SessionID != "session-gemini-qrs456" {
		t.Errorf("SessionID = %q, want %q", meta.SessionID, "session-gemini-qrs456")
	}
	if meta.CLIType != protocol.CLIGemini {
		t.Errorf("CLIType = %q, want %q", meta.CLIType, protocol.CLIGemini)
	}
	if meta.Model != "gemini-2.5-pro" {
		t.Errorf("Model = %q, want %q", meta.Model, "gemini-2.5-pro")
	}

	// Count event types
	counts := make(map[protocol.AgentEventType]int)
	for _, e := range events {
		counts[e.EventType]++
		if e.CLIType != protocol.CLIGemini {
			t.Errorf("event CLIType = %q, want gemini", e.CLIType)
		}
	}

	// Verify we got the expected event types from the sample
	if counts[protocol.EventSessionStart] != 1 {
		t.Errorf("session_start count = %d, want 1", counts[protocol.EventSessionStart])
	}
	if counts[protocol.EventToolStart] < 1 {
		t.Errorf("tool_start count = %d, want >= 1", counts[protocol.EventToolStart])
	}
	if counts[protocol.EventToolDone] < 1 {
		t.Errorf("tool_done count = %d, want >= 1", counts[protocol.EventToolDone])
	}
	if counts[protocol.EventMessage] < 1 {
		t.Errorf("message count = %d, want >= 1", counts[protocol.EventMessage])
	}
	if counts[protocol.EventThinking] >= 1 {
		// Good: we have thinking events from thoughts fields
	}
	if counts[protocol.EventIdle] < 1 {
		t.Errorf("idle count = %d, want >= 1", counts[protocol.EventIdle])
	}

	t.Logf("parsed %d events: %v", len(events), counts)
}

func TestParseDiffMode(t *testing.T) {
	data, err := os.ReadFile(testdataPath("sample.json"))
	if err != nil {
		t.Fatalf("failed to read test fixture: %v", err)
	}

	p := New()

	// First parse: should produce events
	events1, err := p.ParseIncremental(data)
	if err != nil {
		t.Fatalf("first ParseIncremental error: %v", err)
	}
	if len(events1) == 0 {
		t.Fatal("first parse: expected events, got none")
	}

	// Second parse with identical data: should produce 0 new events
	events2, err := p.ParseIncremental(data)
	if err != nil {
		t.Fatalf("second ParseIncremental error: %v", err)
	}
	if len(events2) != 0 {
		t.Errorf("second parse: expected 0 events, got %d", len(events2))
	}
}

func TestParseNewMessages(t *testing.T) {
	data, err := os.ReadFile(testdataPath("sample.json"))
	if err != nil {
		t.Fatalf("failed to read test fixture: %v", err)
	}

	p := New()

	// First parse
	events1, err := p.ParseIncremental(data)
	if err != nil {
		t.Fatalf("first ParseIncremental error: %v", err)
	}
	firstCount := len(events1)
	if firstCount == 0 {
		t.Fatal("first parse should produce events")
	}

	// Append a new message to the JSON
	var doc map[string]any
	if err := json.Unmarshal(data, &doc); err != nil {
		t.Fatalf("unmarshal error: %v", err)
	}

	messages := doc["messages"].([]any)
	newMsg := map[string]any{
		"type":      "gemini",
		"timestamp": "2026-02-24T10:31:00.000Z",
		"content":   "Here is a new response.",
		"toolCalls": []any{
			map[string]any{
				"name":   "read_file",
				"args":   map[string]any{"path": "/tmp/new.go"},
				"result": "package main",
			},
		},
		"tokens": map[string]any{
			"input":  6000,
			"output": 400,
			"cached": 5000,
		},
	}
	messages = append(messages, newMsg)
	doc["messages"] = messages
	doc["lastUpdated"] = "2026-02-24T10:31:00.000Z"

	updatedData, err := json.Marshal(doc)
	if err != nil {
		t.Fatalf("marshal error: %v", err)
	}

	// Second parse with appended message
	events2, err := p.ParseIncremental(updatedData)
	if err != nil {
		t.Fatalf("second ParseIncremental error: %v", err)
	}

	// Should only get events for the new message:
	// tool_start + tool_done + message + idle = 4 events
	if len(events2) != 4 {
		t.Errorf("second parse: expected 4 new events, got %d", len(events2))
		for i, e := range events2 {
			t.Logf("  event[%d]: %s", i, e.EventType)
		}
	}

	// Verify the new events are for the new message
	hasToolStart := false
	hasToolDone := false
	hasMessage := false
	hasIdle := false
	for _, e := range events2 {
		switch e.EventType {
		case protocol.EventToolStart:
			hasToolStart = true
			if e.ToolName != "read_file" {
				t.Errorf("ToolName = %q, want read_file", e.ToolName)
			}
		case protocol.EventToolDone:
			hasToolDone = true
		case protocol.EventMessage:
			hasMessage = true
		case protocol.EventIdle:
			hasIdle = true
		}
	}

	if !hasToolStart {
		t.Error("missing tool_start event in new events")
	}
	if !hasToolDone {
		t.Error("missing tool_done event in new events")
	}
	if !hasMessage {
		t.Error("missing message event in new events")
	}
	if !hasIdle {
		t.Error("missing idle event in new events")
	}
}

func TestParseThinking(t *testing.T) {
	doc := transcript{
		LastUpdated: "2026-02-24T10:30:00.000Z",
		SessionID:   "test-thinking",
		Messages: []message{
			{
				Type:      "gemini",
				Timestamp: "2026-02-24T10:30:00.000Z",
				Model:     "gemini-2.5-pro",
				Thoughts:  json.RawMessage(`[{"subject":"Analyzing","description":"I need to analyze the user's request carefully before responding."}]`),
				Content:   json.RawMessage(`"Let me look into that."`),
			},
		},
	}

	data, err := json.Marshal(doc)
	if err != nil {
		t.Fatalf("marshal error: %v", err)
	}

	p := New()
	events, err := p.ParseIncremental(data)
	if err != nil {
		t.Fatalf("ParseIncremental error: %v", err)
	}

	// Expect: session_start + thinking + message = 3
	thinkingCount := 0
	for _, e := range events {
		if e.EventType == protocol.EventThinking {
			thinkingCount++
			text, ok := e.Metadata["text"].(string)
			if !ok || text == "" {
				t.Error("thinking event should have non-empty text in metadata")
			}
			if e.AgentID != "gemini-test-thinking" {
				t.Errorf("AgentID = %q, want gemini-test-thinking", e.AgentID)
			}
		}
	}

	if thinkingCount != 1 {
		t.Errorf("thinking event count = %d, want 1", thinkingCount)
	}
}

func TestParseToolCalls(t *testing.T) {
	doc := transcript{
		LastUpdated: "2026-02-24T10:30:00.000Z",
		SessionID:   "test-tools",
		Messages: []message{
			{
				Type:      "gemini",
				Timestamp: "2026-02-24T10:30:00.000Z",
				Model:     "gemini-2.5-pro",
				Content:   json.RawMessage(`"Reading files."`),
				ToolCalls: []toolCall{
					{
						Name:   "read_file",
						Args:   map[string]any{"path": "/tmp/a.go"},
						Result: "package main\nfunc main() {}",
					},
					{
						Name:   "edit_file",
						Args:   map[string]any{"path": "/tmp/b.go", "content": "new content"},
						Result: "Edit applied successfully.",
					},
				},
			},
		},
	}

	data, err := json.Marshal(doc)
	if err != nil {
		t.Fatalf("marshal error: %v", err)
	}

	p := New()
	events, err := p.ParseIncremental(data)
	if err != nil {
		t.Fatalf("ParseIncremental error: %v", err)
	}

	// Count tool events
	toolStarts := 0
	toolDones := 0
	var toolNames []string
	for _, e := range events {
		switch e.EventType {
		case protocol.EventToolStart:
			toolStarts++
			toolNames = append(toolNames, e.ToolName)
			if e.ToolStatus != protocol.ToolRunning {
				t.Errorf("tool_start status = %q, want running", e.ToolStatus)
			}
			if e.ToolInput == "" {
				t.Error("tool_start should have ToolInput")
			}
		case protocol.EventToolDone:
			toolDones++
			if e.ToolStatus != protocol.ToolSuccess {
				t.Errorf("tool_done status = %q, want success", e.ToolStatus)
			}
		}
	}

	if toolStarts != 2 {
		t.Errorf("tool_start count = %d, want 2", toolStarts)
	}
	if toolDones != 2 {
		t.Errorf("tool_done count = %d, want 2", toolDones)
	}
	if len(toolNames) >= 2 {
		if toolNames[0] != "read_file" {
			t.Errorf("first tool = %q, want read_file", toolNames[0])
		}
		if toolNames[1] != "edit_file" {
			t.Errorf("second tool = %q, want edit_file", toolNames[1])
		}
	}
}

func TestParseTokens(t *testing.T) {
	doc := transcript{
		LastUpdated: "2026-02-24T10:30:00.000Z",
		SessionID:   "test-tokens",
		Messages: []message{
			{
				Type:      "gemini",
				Timestamp: "2026-02-24T10:30:00.000Z",
				Model:     "gemini-2.5-pro",
				Content:   json.RawMessage(`"Done."`),
				Tokens: &tokens{
					Input:    1250,
					Output:   340,
					Cached:   800,
					Thoughts: 180,
					Tool:     420,
					Total:    1590,
				},
			},
		},
	}

	data, err := json.Marshal(doc)
	if err != nil {
		t.Fatalf("marshal error: %v", err)
	}

	p := New()
	events, err := p.ParseIncremental(data)
	if err != nil {
		t.Fatalf("ParseIncremental error: %v", err)
	}

	// Find the idle event with tokens
	var idleEvent *protocol.AgentEvent
	for i, e := range events {
		if e.EventType == protocol.EventIdle {
			idleEvent = &events[i]
			break
		}
	}

	if idleEvent == nil {
		t.Fatal("no idle event found")
	}
	if idleEvent.Tokens == nil {
		t.Fatal("idle event Tokens is nil")
	}

	tok := idleEvent.Tokens
	if tok.Input != 1250 {
		t.Errorf("Tokens.Input = %d, want 1250", tok.Input)
	}
	if tok.Output != 340 {
		t.Errorf("Tokens.Output = %d, want 340", tok.Output)
	}
	if tok.Cached != 800 {
		t.Errorf("Tokens.Cached = %d, want 800", tok.Cached)
	}
	if tok.Total != 1250+340 {
		t.Errorf("Tokens.Total = %d, want %d", tok.Total, 1250+340)
	}
}

func TestSessionInfo(t *testing.T) {
	doc := transcript{
		LastUpdated: "2026-02-24T10:30:45.000Z",
		StartTime:   "2026-02-24T10:30:00.000Z",
		SessionID:   "session-gemini-xyz789",
		Messages: []message{
			{
				Type:      "user",
				Timestamp: "2026-02-24T10:30:00.000Z",
				Content:   json.RawMessage(`[{"text": "Hello"}]`),
			},
		},
	}

	data, err := json.Marshal(doc)
	if err != nil {
		t.Fatalf("marshal error: %v", err)
	}

	p := New()
	_, err = p.ParseIncremental(data)
	if err != nil {
		t.Fatalf("ParseIncremental error: %v", err)
	}

	meta := p.SessionInfo()

	if meta.SessionID != "session-gemini-xyz789" {
		t.Errorf("SessionID = %q, want session-gemini-xyz789", meta.SessionID)
	}
	if meta.CLIType != protocol.CLIGemini {
		t.Errorf("CLIType = %q, want gemini", meta.CLIType)
	}
	// Model comes from the first gemini message; this test only has user messages, so model is empty
	if meta.Model != "" {
		t.Errorf("Model = %q, want empty (no gemini messages in this transcript)", meta.Model)
	}
	if meta.StartTime.IsZero() {
		t.Error("StartTime should not be zero")
	}

	// Test Reset
	p.Reset()
	metaAfter := p.SessionInfo()
	if metaAfter.SessionID != "" {
		t.Errorf("after Reset, SessionID = %q, want empty", metaAfter.SessionID)
	}
}

func TestParseInvalidJSON(t *testing.T) {
	p := New()
	_, err := p.ParseIncremental([]byte(`{invalid json`))
	if err == nil {
		t.Error("expected error for invalid JSON, got nil")
	}
}

func TestToolInputTruncation(t *testing.T) {
	// Create a tool call with very long args
	longPath := "/very/long/path/" + string(make([]byte, 300))
	doc := transcript{
		LastUpdated: "2026-02-24T10:30:00.000Z",
		SessionID:   "test-truncate",
		Messages: []message{
			{
				Type:      "gemini",
				Timestamp: "2026-02-24T10:30:00.000Z",
				Model:     "gemini-2.5-pro",
				Content:   json.RawMessage(`"Reading."`),
				ToolCalls: []toolCall{
					{
						Name:   "read_file",
						Args:   map[string]any{"path": longPath},
						Result: "ok",
					},
				},
			},
		},
	}

	data, err := json.Marshal(doc)
	if err != nil {
		t.Fatalf("marshal error: %v", err)
	}

	p := New()
	events, err := p.ParseIncremental(data)
	if err != nil {
		t.Fatalf("ParseIncremental error: %v", err)
	}

	for _, e := range events {
		if e.EventType == protocol.EventToolStart {
			// 200 chars + "..." = 203
			if len(e.ToolInput) > 203 {
				t.Errorf("ToolInput length = %d, should be <= 203 (200 + ...)", len(e.ToolInput))
			}
			return
		}
	}
	t.Error("no tool_start event found")
}
