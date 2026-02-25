package codex

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/joneshong/agent-vista/internal/protocol"
)

func testdataPath(name string) string {
	return filepath.Join("..", "..", "..", "testdata", "codex", name)
}

func TestDetect(t *testing.T) {
	p := New()

	cases := []struct {
		path string
		want bool
	}{
		{"~/.codex/sessions/rollout-001.jsonl", true},
		{"/Users/me/.codex/sessions/sess.jsonl", true},
		{"/path/to/testdata/codex/sample.jsonl", true},
		{"/some/path/.claude/conversations/file.jsonl", false},
		{"/some/path/.codex/sessions/file.json", false}, // wrong extension
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
	if meta.SessionID != "rollout-2026-02-24T10-15-00-xyz789" {
		t.Errorf("SessionID = %q, want %q", meta.SessionID, "rollout-2026-02-24T10-15-00-xyz789")
	}
	if meta.CLIType != protocol.CLICodex {
		t.Errorf("CLIType = %q, want %q", meta.CLIType, protocol.CLICodex)
	}
	// Model is not set from session_meta payload (model_provider != model name)

	// Count event types
	counts := make(map[protocol.AgentEventType]int)
	for _, e := range events {
		counts[e.EventType]++
		if e.CLIType != protocol.CLICodex {
			t.Errorf("event CLIType = %q, want codex", e.CLIType)
		}
	}

	// sample.jsonl has:
	// 1 session_meta     -> 1 session_start
	// 3 function_call    -> 3 tool_start
	// 3 function_call_output -> 3 tool_done
	// 1 token_count      -> 1 idle
	// 1 task_complete    -> 1 session_end
	if counts[protocol.EventSessionStart] != 1 {
		t.Errorf("session_start count = %d, want 1", counts[protocol.EventSessionStart])
	}
	if counts[protocol.EventToolStart] != 3 {
		t.Errorf("tool_start count = %d, want 3", counts[protocol.EventToolStart])
	}
	if counts[protocol.EventToolDone] != 3 {
		t.Errorf("tool_done count = %d, want 3", counts[protocol.EventToolDone])
	}
	if counts[protocol.EventIdle] != 1 {
		t.Errorf("idle count = %d, want 1", counts[protocol.EventIdle])
	}
	if counts[protocol.EventSessionEnd] != 1 {
		t.Errorf("session_end count = %d, want 1", counts[protocol.EventSessionEnd])
	}

	totalExpected := 9
	if len(events) != totalExpected {
		t.Errorf("total events = %d, want %d", len(events), totalExpected)
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

	// Feed data in 80-byte chunks to test partial line buffering
	chunkSize := 80
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

func TestParseSessionMeta(t *testing.T) {
	line := `{"timestamp":"2026-02-24T10:15:00.000Z","type":"session_meta","payload":{"id":"test-sess-001","cwd":"/Users/joneshong/workshop/core","model_provider":"openai","cli_version":"0.1.2","source":"interactive"}}`

	p := New()
	events, err := p.ParseIncremental([]byte(line + "\n"))
	if err != nil {
		t.Fatalf("error: %v", err)
	}

	if len(events) != 1 {
		t.Fatalf("expected 1 event, got %d", len(events))
	}

	evt := events[0]
	if evt.EventType != protocol.EventSessionStart {
		t.Errorf("EventType = %q, want session_start", evt.EventType)
	}
	if evt.SessionID != "test-sess-001" {
		t.Errorf("SessionID = %q, want test-sess-001", evt.SessionID)
	}
	if evt.AgentID != "codex-test-sess-001" {
		t.Errorf("AgentID = %q, want codex-test-sess-001", evt.AgentID)
	}

	meta := p.SessionInfo()
	// Model is not populated from session_meta (model_provider is the LLM provider, not model name)
	if meta.ProjectDir != "/Users/joneshong/workshop/core" {
		t.Errorf("ProjectDir = %q, want /Users/joneshong/workshop/core", meta.ProjectDir)
	}
	if meta.CLIType != protocol.CLICodex {
		t.Errorf("CLIType = %q, want codex", meta.CLIType)
	}

	// Verify metadata fields (parser maps model_provider -> "provider", cli_version -> "version")
	if evt.Metadata["provider"] != "openai" {
		t.Errorf("Metadata[provider] = %v, want openai", evt.Metadata["provider"])
	}
	if evt.Metadata["version"] != "0.1.2" {
		t.Errorf("Metadata[version] = %v, want 0.1.2", evt.Metadata["version"])
	}
}

func TestParseFunctionCallAndOutput(t *testing.T) {
	lines := `{"timestamp":"2026-02-24T10:15:05.234Z","type":"response_item","payload":{"type":"function_call","name":"read_file","arguments":"{\"path\":\"/tmp/test.go\"}","call_id":"call_abc123"}}
{"timestamp":"2026-02-24T10:15:06.012Z","type":"response_item","payload":{"type":"function_call_output","call_id":"call_abc123","output":"file contents here","exit_code":0}}
`

	p := New()
	events, err := p.ParseIncremental([]byte(lines))
	if err != nil {
		t.Fatalf("error: %v", err)
	}

	if len(events) != 2 {
		t.Fatalf("expected 2 events, got %d", len(events))
	}

	// tool_start
	if events[0].EventType != protocol.EventToolStart {
		t.Errorf("event[0] type = %q, want tool_start", events[0].EventType)
	}
	if events[0].ToolName != "read_file" {
		t.Errorf("ToolName = %q, want read_file", events[0].ToolName)
	}
	if events[0].ToolStatus != protocol.ToolRunning {
		t.Errorf("ToolStatus = %q, want running", events[0].ToolStatus)
	}
	if events[0].ToolInput == "" {
		t.Error("ToolInput should not be empty")
	}
	if events[0].Metadata["call_id"] != "call_abc123" {
		t.Errorf("Metadata[call_id] = %v, want call_abc123", events[0].Metadata["call_id"])
	}

	// tool_done
	if events[1].EventType != protocol.EventToolDone {
		t.Errorf("event[1] type = %q, want tool_done", events[1].EventType)
	}
	if events[1].ToolStatus != protocol.ToolSuccess {
		t.Errorf("ToolStatus = %q, want success", events[1].ToolStatus)
	}

	// Test with non-zero exit code (error)
	errorLine := `{"timestamp":"2026-02-24T10:15:07.000Z","type":"response_item","payload":{"type":"function_call_output","call_id":"call_err","output":"command failed","exit_code":1}}
`
	events2, _ := p.ParseIncremental([]byte(errorLine))
	if len(events2) != 1 {
		t.Fatalf("expected 1 event, got %d", len(events2))
	}
	if events2[0].ToolStatus != protocol.ToolError {
		t.Errorf("ToolStatus for exit_code=1 = %q, want error", events2[0].ToolStatus)
	}
}

func TestParseTokenCount(t *testing.T) {
	line := `{"timestamp":"2026-02-24T10:15:30.000Z","type":"event_msg","payload":{"type":"token_count","info":{"total_token_usage":{"input_tokens":4520,"output_tokens":1890,"total_tokens":6410}}}}
`

	p := New()
	events, err := p.ParseIncremental([]byte(line))
	if err != nil {
		t.Fatalf("error: %v", err)
	}

	if len(events) != 1 {
		t.Fatalf("expected 1 event, got %d", len(events))
	}

	evt := events[0]
	if evt.EventType != protocol.EventIdle {
		t.Errorf("EventType = %q, want idle", evt.EventType)
	}
	if evt.Tokens == nil {
		t.Fatal("Tokens is nil")
	}
	if evt.Tokens.Input != 4520 {
		t.Errorf("Tokens.Input = %d, want 4520", evt.Tokens.Input)
	}
	if evt.Tokens.Output != 1890 {
		t.Errorf("Tokens.Output = %d, want 1890", evt.Tokens.Output)
	}
	if evt.Tokens.Total != 6410 {
		t.Errorf("Tokens.Total = %d, want 6410", evt.Tokens.Total)
	}
	if evt.CLIType != protocol.CLICodex {
		t.Errorf("CLIType = %q, want codex", evt.CLIType)
	}
}

func TestParseTaskComplete(t *testing.T) {
	line := `{"timestamp":"2026-02-24T10:15:32.000Z","type":"event_msg","payload":{"type":"task_complete","last_agent_message":"Added rate limiting to authentication service."}}
`

	p := New()
	events, err := p.ParseIncremental([]byte(line))
	if err != nil {
		t.Fatalf("error: %v", err)
	}

	if len(events) != 1 {
		t.Fatalf("expected 1 event, got %d", len(events))
	}

	evt := events[0]
	if evt.EventType != protocol.EventSessionEnd {
		t.Errorf("EventType = %q, want session_end", evt.EventType)
	}
	// summary is populated from payload.last_agent_message
	if evt.Metadata["summary"] != "Added rate limiting to authentication service." {
		t.Errorf("Metadata[summary] = %v", evt.Metadata["summary"])
	}
	if evt.CLIType != protocol.CLICodex {
		t.Errorf("CLIType = %q, want codex", evt.CLIType)
	}
}

func TestMalformedLineSkipped(t *testing.T) {
	data := `not valid json
{"timestamp":"2026-02-24T10:15:00.000Z","type":"session_meta","payload":{"id":"s1","cwd":"/tmp","model_provider":"openai","cli_version":"0.1.0","source":"interactive"}}
{broken json too
`

	p := New()
	events, err := p.ParseIncremental([]byte(data))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Should get 1 event (the valid session_meta), malformed lines skipped
	if len(events) != 1 {
		t.Errorf("expected 1 event, got %d", len(events))
	}
	if events[0].EventType != protocol.EventSessionStart {
		t.Errorf("EventType = %q, want session_start", events[0].EventType)
	}
}
