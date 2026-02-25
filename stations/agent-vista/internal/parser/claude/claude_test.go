package claude

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/joneshong/agent-vista/internal/protocol"
)

func testdataPath(name string) string {
	return filepath.Join("..", "..", "..", "testdata", "claude", name)
}

func TestDetect(t *testing.T) {
	p := New()

	cases := []struct {
		path string
		want bool
	}{
		{"~/.claude/projects/abc123/conversations/001.jsonl", true},
		{"/Users/me/.claude/projects/hash/conversations/sess.jsonl", true},
		{"/path/to/testdata/claude/sample.jsonl", true},
		{"/some/path/.codex/sessions/file.jsonl", false},
		{"/some/path/.claude/file.json", false}, // wrong extension
		{"random.txt", false},
	}

	for _, tc := range cases {
		if got := p.Detect(tc.path); got != tc.want {
			t.Errorf("Detect(%q) = %v, want %v", tc.path, got, tc.want)
		}
	}
}

func TestParseIncrementalFullFile(t *testing.T) {
	data, err := os.ReadFile(testdataPath("sample.jsonl"))
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
	if meta.SessionID != "sess-claude-abc123" {
		t.Errorf("SessionID = %q, want %q", meta.SessionID, "sess-claude-abc123")
	}
	if meta.CLIType != protocol.CLIClaude {
		t.Errorf("CLIType = %q, want %q", meta.CLIType, protocol.CLIClaude)
	}
	// Model is populated from the first assistant message (line 2 in sample.jsonl)
	if meta.Model != "claude-opus-4-6" {
		t.Errorf("Model = %q, want %q", meta.Model, "claude-opus-4-6")
	}

	// Count event types
	counts := make(map[protocol.AgentEventType]int)
	for _, e := range events {
		counts[e.EventType]++
		// All events should have CLIClaude
		if e.CLIType != protocol.CLIClaude {
			t.Errorf("event CLIType = %q, want claude", e.CLIType)
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
	if counts[protocol.EventIdle] != 1 {
		t.Errorf("idle count = %d, want 1", counts[protocol.EventIdle])
	}

	t.Logf("parsed %d events: %v", len(events), counts)
}

func TestParseIncrementalChunked(t *testing.T) {
	data, err := os.ReadFile(testdataPath("sample.jsonl"))
	if err != nil {
		t.Fatalf("failed to read test fixture: %v", err)
	}

	p := New()
	var allEvents []protocol.AgentEvent

	// Feed data in 100-byte chunks to test partial line buffering
	chunkSize := 100
	for i := 0; i < len(data); i += chunkSize {
		end := i + chunkSize
		if end > len(data) {
			end = len(data)
		}
		events, err := p.ParseIncremental(data[i:end])
		if err != nil {
			t.Fatalf("ParseIncremental chunk [%d:%d] error: %v", i, end, err)
		}
		allEvents = append(allEvents, events...)
	}

	// Should produce same number of events as full-file parse
	p2 := New()
	fullEvents, _ := p2.ParseIncremental(data)

	if len(allEvents) != len(fullEvents) {
		t.Errorf("chunked parse produced %d events, full parse produced %d", len(allEvents), len(fullEvents))
	}
}

// TestParseAutoInit verifies that auto-initialization fires on the first record
// containing a sessionId (a progress record here), and that the model is later
// populated from the first assistant message's message.model field.
func TestParseAutoInit(t *testing.T) {
	// Line 1: progress record — triggers auto-init (session_start), model unknown yet
	// Line 2: assistant record — model now populated via parseAssistant
	lines := `{"type":"progress","timestamp":"2026-02-24T10:00:00.000Z","sessionId":"test-sess-001","cwd":"/tmp/project","version":"1.0.34","data":{"type":"hook_progress","hookEvent":"SessionStart"}}
{"type":"assistant","timestamp":"2026-02-24T10:00:05.000Z","sessionId":"test-sess-001","message":{"model":"claude-opus-4-6","role":"assistant","content":[{"type":"text","text":"Hello!"}],"stop_reason":"end_turn"}}
`

	p := New()
	events, err := p.ParseIncremental([]byte(lines))
	if err != nil {
		t.Fatalf("error: %v", err)
	}

	// Expect: session_start (from line 1) + message (from line 2) = 2 events
	if len(events) != 2 {
		t.Fatalf("expected 2 events, got %d", len(events))
	}

	evt := events[0]
	if evt.EventType != protocol.EventSessionStart {
		t.Errorf("EventType = %q, want session_start", evt.EventType)
	}
	if evt.SessionID != "test-sess-001" {
		t.Errorf("SessionID = %q, want test-sess-001", evt.SessionID)
	}
	if evt.AgentID != "claude-test-sess-001" {
		t.Errorf("AgentID = %q, want claude-test-sess-001", evt.AgentID)
	}

	// After the second line, model should be set
	meta := p.SessionInfo()
	if meta.Model != "claude-opus-4-6" {
		t.Errorf("Model = %q, want claude-opus-4-6", meta.Model)
	}
	if meta.ProjectDir != "/tmp/project" {
		t.Errorf("ProjectDir = %q, want /tmp/project", meta.ProjectDir)
	}
}

func TestParseToolUseAndResult(t *testing.T) {
	// Line 1: assistant (init record) — triggers auto-init → session_start only
	// Line 2: assistant with tool_use — tool_start event
	// Line 3: user with tool_result — tool_done event
	// Total: 3 events
	lines := `{"type":"assistant","timestamp":"2026-02-24T10:00:00.000Z","sessionId":"s1","message":{"model":"claude-opus-4-6","role":"assistant","content":[{"type":"text","text":"Starting..."}],"stop_reason":"end_turn"}}
{"type":"assistant","timestamp":"2026-02-24T10:00:05.000Z","sessionId":"s1","message":{"model":"claude-opus-4-6","role":"assistant","content":[{"type":"tool_use","id":"toolu_001","name":"Read","input":{"file_path":"/tmp/test.go"}}],"stop_reason":"tool_use"}}
{"type":"user","timestamp":"2026-02-24T10:00:06.000Z","sessionId":"s1","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"toolu_001","content":[{"type":"text","text":"file contents here"}],"is_error":false}]}}
`

	p := New()
	events, err := p.ParseIncremental([]byte(lines))
	if err != nil {
		t.Fatalf("error: %v", err)
	}

	// session_start + tool_start + tool_done = 3
	if len(events) != 3 {
		t.Fatalf("expected 3 events, got %d: %v", len(events), eventTypes(events))
	}

	// event[0]: session_start (auto-init from line 1)
	if events[0].EventType != protocol.EventSessionStart {
		t.Errorf("event[0] type = %q, want session_start", events[0].EventType)
	}

	// event[1]: tool_start (line 2)
	if events[1].EventType != protocol.EventToolStart {
		t.Errorf("event[1] type = %q, want tool_start", events[1].EventType)
	}
	if events[1].ToolName != "Read" {
		t.Errorf("ToolName = %q, want Read", events[1].ToolName)
	}
	if events[1].ToolStatus != protocol.ToolRunning {
		t.Errorf("ToolStatus = %q, want running", events[1].ToolStatus)
	}

	// event[2]: tool_done (line 3)
	if events[2].EventType != protocol.EventToolDone {
		t.Errorf("event[2] type = %q, want tool_done", events[2].EventType)
	}
	if events[2].ToolStatus != protocol.ToolSuccess {
		t.Errorf("ToolStatus = %q, want success", events[2].ToolStatus)
	}
}

func TestParseToolError(t *testing.T) {
	// Line 1: progress record — triggers auto-init → session_start only
	// Line 2: user with is_error:true — tool_done(error) event
	// Total: 2 events
	lines := `{"type":"progress","timestamp":"2026-02-24T10:00:00.000Z","sessionId":"s1","data":{"type":"hook_progress"}}
{"type":"user","timestamp":"2026-02-24T10:00:06.000Z","sessionId":"s1","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"toolu_err","content":[{"type":"text","text":"file not found"}],"is_error":true}]}}
`

	p := New()
	events, _ := p.ParseIncremental([]byte(lines))

	if len(events) != 2 {
		t.Fatalf("expected 2 events, got %d: %v", len(events), eventTypes(events))
	}

	// event[0]: session_start
	if events[0].EventType != protocol.EventSessionStart {
		t.Errorf("event[0] type = %q, want session_start", events[0].EventType)
	}

	// event[1]: tool_done with error
	if events[1].EventType != protocol.EventToolDone {
		t.Errorf("event[1] type = %q, want tool_done", events[1].EventType)
	}
	if events[1].ToolStatus != protocol.ToolError {
		t.Errorf("ToolStatus = %q, want error", events[1].ToolStatus)
	}
}

func TestParseSubAgent(t *testing.T) {
	// Line 1: assistant — triggers auto-init → session_start only
	// Line 2: assistant with Task tool_use → sub_agent_start
	// Line 3: progress with agent_progress → sub_agent_start
	// Total: 3 events
	lines := `{"type":"assistant","timestamp":"2026-02-24T10:00:00.000Z","sessionId":"s1","message":{"model":"claude-opus-4-6","role":"assistant","content":[{"type":"text","text":"Starting..."}],"stop_reason":"end_turn"}}
{"type":"assistant","timestamp":"2026-02-24T10:00:08.000Z","sessionId":"s1","message":{"model":"claude-opus-4-6","role":"assistant","content":[{"type":"tool_use","id":"toolu_task","name":"Task","input":{"description":"explore codebase","agent":"explorer"}}],"stop_reason":"tool_use"}}
{"type":"progress","timestamp":"2026-02-24T10:00:09.000Z","sessionId":"s1","data":{"type":"agent_progress","agent_type":"explorer","status":"running","description":"Exploring...","parent_tool_use_id":"toolu_task"}}
`

	p := New()
	events, _ := p.ParseIncremental([]byte(lines))

	if len(events) != 3 {
		t.Fatalf("expected 3 events, got %d: %v", len(events), eventTypes(events))
	}

	// event[0]: session_start
	if events[0].EventType != protocol.EventSessionStart {
		t.Errorf("event[0] type = %q, want session_start", events[0].EventType)
	}

	// event[1]: Task tool_use → sub_agent_start
	if events[1].EventType != protocol.EventSubAgentStart {
		t.Errorf("event[1] type = %q, want sub_agent_start", events[1].EventType)
	}
	if !events[1].SubAgent {
		t.Error("event[1] SubAgent should be true")
	}

	// event[2]: progress → sub_agent_start (running)
	if events[2].EventType != protocol.EventSubAgentStart {
		t.Errorf("event[2] type = %q, want sub_agent_start", events[2].EventType)
	}
}

func TestParseTurnDuration(t *testing.T) {
	// Line 1: progress — triggers auto-init → session_start only
	// Line 2: system/turn_duration → idle event
	// Total: 2 events
	lines := `{"type":"progress","timestamp":"2026-02-24T10:00:00.000Z","sessionId":"s1","data":{"type":"hook_progress"}}
{"type":"system","subtype":"turn_duration","timestamp":"2026-02-24T10:01:00.000Z","sessionId":"s1","duration_ms":57000,"input_tokens":12450,"output_tokens":3280,"cache_read_tokens":8200,"cache_write_tokens":1500}
`

	p := New()
	events, _ := p.ParseIncremental([]byte(lines))

	if len(events) != 2 {
		t.Fatalf("expected 2 events, got %d: %v", len(events), eventTypes(events))
	}

	// Find the idle event
	var idleEvt *protocol.AgentEvent
	for i := range events {
		if events[i].EventType == protocol.EventIdle {
			idleEvt = &events[i]
			break
		}
	}
	if idleEvt == nil {
		t.Fatal("no idle event found")
	}

	if idleEvt.Tokens == nil {
		t.Fatal("Tokens is nil")
	}
	if idleEvt.Tokens.Input != 12450 {
		t.Errorf("Tokens.Input = %d, want 12450", idleEvt.Tokens.Input)
	}
	if idleEvt.Tokens.Output != 3280 {
		t.Errorf("Tokens.Output = %d, want 3280", idleEvt.Tokens.Output)
	}
	if idleEvt.Tokens.Cached != 8200 {
		t.Errorf("Tokens.Cached = %d, want 8200", idleEvt.Tokens.Cached)
	}
	if idleEvt.Tokens.Total != 12450+3280 {
		t.Errorf("Tokens.Total = %d, want %d", idleEvt.Tokens.Total, 12450+3280)
	}
}

func TestReset(t *testing.T) {
	p := New()
	p.ParseIncremental([]byte(`{"type":"progress","timestamp":"2026-02-24T10:00:00.000Z","sessionId":"s1","cwd":"/tmp","version":"1.0","data":{"type":"hook_progress"}}` + "\n"))

	if p.SessionInfo().SessionID != "s1" {
		t.Fatal("session not set before reset")
	}

	p.Reset()

	if p.SessionInfo().SessionID != "" {
		t.Error("session not cleared after reset")
	}
	if p.initialized {
		t.Error("initialized not cleared after reset")
	}
}

func TestMalformedLineSkipped(t *testing.T) {
	data := `not valid json
{"type":"progress","timestamp":"2026-02-24T10:00:00.000Z","sessionId":"s1","cwd":"/tmp","version":"1.0","data":{"type":"hook_progress"}}
{broken json too
`

	p := New()
	events, err := p.ParseIncremental([]byte(data))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Should get 1 event (session_start from the valid progress line), malformed lines skipped
	if len(events) != 1 {
		t.Errorf("expected 1 event, got %d", len(events))
	}
	if events[0].EventType != protocol.EventSessionStart {
		t.Errorf("event type = %q, want session_start", events[0].EventType)
	}
}

func TestMultipleContentBlocks(t *testing.T) {
	// Line 1: assistant — triggers auto-init → session_start only
	// Line 2: assistant with text + tool_use → message + tool_start = 2 events
	// Total: 3 events
	lines := `{"type":"assistant","timestamp":"2026-02-24T10:00:00.000Z","sessionId":"s1","message":{"model":"claude-opus-4-6","role":"assistant","content":[{"type":"text","text":"Starting..."}],"stop_reason":"end_turn"}}
{"type":"assistant","timestamp":"2026-02-24T10:00:05.000Z","sessionId":"s1","message":{"model":"claude-opus-4-6","role":"assistant","content":[{"type":"text","text":"Let me read the file."},{"type":"tool_use","id":"t1","name":"Read","input":{"file_path":"/tmp/x"}}],"stop_reason":"tool_use"}}
`

	p := New()
	events, _ := p.ParseIncremental([]byte(lines))

	// session_start + message + tool_start = 3
	if len(events) != 3 {
		t.Fatalf("expected 3 events (session_start + text + tool_use), got %d: %v", len(events), eventTypes(events))
	}
	if events[0].EventType != protocol.EventSessionStart {
		t.Errorf("event[0] = %q, want session_start", events[0].EventType)
	}
	if events[1].EventType != protocol.EventMessage {
		t.Errorf("event[1] = %q, want message", events[1].EventType)
	}
	if events[2].EventType != protocol.EventToolStart {
		t.Errorf("event[2] = %q, want tool_start", events[2].EventType)
	}
}

// eventTypes is a helper for test failure messages.
func eventTypes(events []protocol.AgentEvent) []protocol.AgentEventType {
	types := make([]protocol.AgentEventType, len(events))
	for i, e := range events {
		types[i] = e.EventType
	}
	return types
}
