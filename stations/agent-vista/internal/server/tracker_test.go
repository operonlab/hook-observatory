package server

import (
	"testing"
	"time"

	"github.com/joneshong/agent-vista/internal/protocol"
)

// helper to create a minimal AgentEvent with sensible defaults.
func makeEvent(eventType protocol.AgentEventType, opts ...func(*protocol.AgentEvent)) protocol.AgentEvent {
	evt := protocol.AgentEvent{
		CLIType:   protocol.CLIClaude,
		SessionID: "sess-001",
		AgentID:   "agent-001",
		Timestamp: time.Now(),
		EventType: eventType,
	}
	for _, fn := range opts {
		fn(&evt)
	}
	return evt
}

func withAgent(id, session string) func(*protocol.AgentEvent) {
	return func(e *protocol.AgentEvent) {
		e.AgentID = id
		e.SessionID = session
	}
}

func withTool(name, input string) func(*protocol.AgentEvent) {
	return func(e *protocol.AgentEvent) {
		e.ToolName = name
		e.ToolInput = input
	}
}

func withTokens(total int) func(*protocol.AgentEvent) {
	return func(e *protocol.AgentEvent) {
		e.Tokens = &protocol.TokenUsage{Total: total}
	}
}

func withCLI(cli protocol.CLIType) func(*protocol.AgentEvent) {
	return func(e *protocol.AgentEvent) {
		e.CLIType = cli
	}
}

// --- Test Cases ---

func TestHandleEventSessionStart(t *testing.T) {
	tracker := NewAgentTracker()
	tracker.HandleEvent(makeEvent(protocol.EventSessionStart))

	agents := tracker.Agents()
	if len(agents) != 1 {
		t.Fatalf("expected 1 agent, got %d", len(agents))
	}

	a := agents[0]
	if a.ID != "agent-001" {
		t.Errorf("expected agent ID 'agent-001', got %q", a.ID)
	}
	if a.Status != protocol.StatusActive {
		t.Errorf("expected status %q, got %q", protocol.StatusActive, a.Status)
	}
	if a.Animation != protocol.AnimIdle {
		t.Errorf("expected animation %q, got %q", protocol.AnimIdle, a.Animation)
	}
	if a.CLIType != protocol.CLIClaude {
		t.Errorf("expected CLI type %q, got %q", protocol.CLIClaude, a.CLIType)
	}
	if a.CurrentTool != "" {
		t.Errorf("expected empty CurrentTool, got %q", a.CurrentTool)
	}
}

func TestHandleEventToolStart(t *testing.T) {
	tracker := NewAgentTracker()
	// Bootstrap agent
	tracker.HandleEvent(makeEvent(protocol.EventSessionStart))

	t.Run("Write tool sets StatusTyping", func(t *testing.T) {
		tracker2 := NewAgentTracker()
		tracker2.HandleEvent(makeEvent(protocol.EventSessionStart))
		tracker2.HandleEvent(makeEvent(protocol.EventToolStart, withTool("Write", "/path/to/file")))

		agents := tracker2.Agents()
		a := agents[0]
		if a.Status != protocol.StatusTyping {
			t.Errorf("expected status %q for Write tool, got %q", protocol.StatusTyping, a.Status)
		}
		if a.Animation != protocol.AnimType {
			t.Errorf("expected animation %q for Write tool, got %q", protocol.AnimType, a.Animation)
		}
		if a.CurrentTool != "Write" {
			t.Errorf("expected CurrentTool 'Write', got %q", a.CurrentTool)
		}
		if a.ToolDetail != "/path/to/file" {
			t.Errorf("expected ToolDetail '/path/to/file', got %q", a.ToolDetail)
		}
	})

	t.Run("Edit tool sets StatusTyping", func(t *testing.T) {
		tracker2 := NewAgentTracker()
		tracker2.HandleEvent(makeEvent(protocol.EventSessionStart))
		tracker2.HandleEvent(makeEvent(protocol.EventToolStart, withTool("Edit", "some edit")))

		agents := tracker2.Agents()
		a := agents[0]
		if a.Status != protocol.StatusTyping {
			t.Errorf("expected status %q for Edit tool, got %q", protocol.StatusTyping, a.Status)
		}
	})

	t.Run("Bash tool sets StatusTyping", func(t *testing.T) {
		tracker2 := NewAgentTracker()
		tracker2.HandleEvent(makeEvent(protocol.EventSessionStart))
		tracker2.HandleEvent(makeEvent(protocol.EventToolStart, withTool("Bash", "ls -la")))

		agents := tracker2.Agents()
		a := agents[0]
		if a.Status != protocol.StatusTyping {
			t.Errorf("expected status %q for Bash tool, got %q", protocol.StatusTyping, a.Status)
		}
	})

	t.Run("Read tool sets StatusReading", func(t *testing.T) {
		tracker2 := NewAgentTracker()
		tracker2.HandleEvent(makeEvent(protocol.EventSessionStart))
		tracker2.HandleEvent(makeEvent(protocol.EventToolStart, withTool("Read", "/some/file")))

		agents := tracker2.Agents()
		a := agents[0]
		if a.Status != protocol.StatusReading {
			t.Errorf("expected status %q for Read tool, got %q", protocol.StatusReading, a.Status)
		}
		if a.Animation != protocol.AnimThink {
			t.Errorf("expected animation %q for Read tool, got %q", protocol.AnimThink, a.Animation)
		}
	})

	t.Run("Grep tool sets StatusReading", func(t *testing.T) {
		tracker2 := NewAgentTracker()
		tracker2.HandleEvent(makeEvent(protocol.EventSessionStart))
		tracker2.HandleEvent(makeEvent(protocol.EventToolStart, withTool("Grep", "pattern")))

		agents := tracker2.Agents()
		a := agents[0]
		if a.Status != protocol.StatusReading {
			t.Errorf("expected status %q for Grep tool, got %q", protocol.StatusReading, a.Status)
		}
	})
}

func TestHandleEventToolDone(t *testing.T) {
	tracker := NewAgentTracker()
	tracker.HandleEvent(makeEvent(protocol.EventSessionStart))
	tracker.HandleEvent(makeEvent(protocol.EventToolStart, withTool("Write", "file.go")))

	// Verify we are in typing state before tool_done
	agents := tracker.Agents()
	if agents[0].Status != protocol.StatusTyping {
		t.Fatalf("precondition failed: expected StatusTyping, got %q", agents[0].Status)
	}

	tracker.HandleEvent(makeEvent(protocol.EventToolDone))

	agents = tracker.Agents()
	a := agents[0]
	if a.Status != protocol.StatusActive {
		t.Errorf("expected status %q after tool_done, got %q", protocol.StatusActive, a.Status)
	}
	if a.Animation != protocol.AnimIdle {
		t.Errorf("expected animation %q after tool_done, got %q", protocol.AnimIdle, a.Animation)
	}
	if a.CurrentTool != "" {
		t.Errorf("expected empty CurrentTool after tool_done, got %q", a.CurrentTool)
	}
	if a.ToolDetail != "" {
		t.Errorf("expected empty ToolDetail after tool_done, got %q", a.ToolDetail)
	}
}

func TestHandleEventThinking(t *testing.T) {
	tracker := NewAgentTracker()
	tracker.HandleEvent(makeEvent(protocol.EventSessionStart))
	tracker.HandleEvent(makeEvent(protocol.EventThinking))

	agents := tracker.Agents()
	a := agents[0]
	if a.Status != protocol.StatusThinking {
		t.Errorf("expected status %q, got %q", protocol.StatusThinking, a.Status)
	}
	if a.Animation != protocol.AnimThink {
		t.Errorf("expected animation %q, got %q", protocol.AnimThink, a.Animation)
	}
	if a.CurrentTool != "" {
		t.Errorf("expected empty CurrentTool, got %q", a.CurrentTool)
	}
}

func TestHandleEventIdle(t *testing.T) {
	tracker := NewAgentTracker()
	tracker.HandleEvent(makeEvent(protocol.EventSessionStart))

	// Send an idle event with token info
	tracker.HandleEvent(makeEvent(protocol.EventIdle, withTokens(500)))

	agents := tracker.Agents()
	a := agents[0]
	if a.Status != protocol.StatusIdle {
		t.Errorf("expected status %q, got %q", protocol.StatusIdle, a.Status)
	}
	if a.Animation != protocol.AnimIdle {
		t.Errorf("expected animation %q, got %q", protocol.AnimIdle, a.Animation)
	}
	if a.TokensTotal != 500 {
		t.Errorf("expected TokensTotal 500, got %d", a.TokensTotal)
	}

	// Send another idle event with more tokens to verify accumulation
	tracker.HandleEvent(makeEvent(protocol.EventIdle, withTokens(300)))

	agents = tracker.Agents()
	a = agents[0]
	if a.TokensTotal != 800 {
		t.Errorf("expected accumulated TokensTotal 800, got %d", a.TokensTotal)
	}
}

func TestHandleEventSessionEnd(t *testing.T) {
	tracker := NewAgentTracker()
	tracker.HandleEvent(makeEvent(protocol.EventSessionStart))

	// Verify agent is active
	agents := tracker.Agents()
	if agents[0].Status != protocol.StatusActive {
		t.Fatalf("precondition: expected StatusActive, got %q", agents[0].Status)
	}

	tracker.HandleEvent(makeEvent(protocol.EventSessionEnd))

	agents = tracker.Agents()
	a := agents[0]
	if a.Status != protocol.StatusOffline {
		t.Errorf("expected status %q, got %q", protocol.StatusOffline, a.Status)
	}
	if a.Animation != protocol.AnimIdle {
		t.Errorf("expected animation %q, got %q", protocol.AnimIdle, a.Animation)
	}
	if a.CurrentTool != "" {
		t.Errorf("expected empty CurrentTool, got %q", a.CurrentTool)
	}
}

func TestAgentsSnapshot(t *testing.T) {
	tracker := NewAgentTracker()
	tracker.HandleEvent(makeEvent(protocol.EventSessionStart))

	// Get a snapshot
	snapshot1 := tracker.Agents()
	if len(snapshot1) != 1 {
		t.Fatalf("expected 1 agent in snapshot, got %d", len(snapshot1))
	}

	// Mutate the snapshot -- this should NOT affect the tracker's internal state
	snapshot1[0].Status = protocol.StatusError
	snapshot1[0].DisplayName = "MUTATED"

	// Get another snapshot and verify it's unaffected
	snapshot2 := tracker.Agents()
	if snapshot2[0].Status == protocol.StatusError {
		t.Error("mutation of snapshot1 affected internal state: Status was changed")
	}
	if snapshot2[0].DisplayName == "MUTATED" {
		t.Error("mutation of snapshot1 affected internal state: DisplayName was changed")
	}
	if snapshot2[0].Status != protocol.StatusActive {
		t.Errorf("expected status %q in fresh snapshot, got %q", protocol.StatusActive, snapshot2[0].Status)
	}
}

func TestTotalEvents(t *testing.T) {
	tracker := NewAgentTracker()

	if tracker.TotalEvents() != 0 {
		t.Fatalf("expected 0 total events initially, got %d", tracker.TotalEvents())
	}

	tracker.HandleEvent(makeEvent(protocol.EventSessionStart))
	if tracker.TotalEvents() != 1 {
		t.Errorf("expected 1 total event, got %d", tracker.TotalEvents())
	}

	tracker.HandleEvent(makeEvent(protocol.EventThinking))
	tracker.HandleEvent(makeEvent(protocol.EventToolStart, withTool("Read", "file.go")))
	tracker.HandleEvent(makeEvent(protocol.EventToolDone))
	if tracker.TotalEvents() != 4 {
		t.Errorf("expected 4 total events, got %d", tracker.TotalEvents())
	}
}

func TestActiveSessionCount(t *testing.T) {
	tracker := NewAgentTracker()

	// No agents yet
	if tracker.ActiveSessionCount() != 0 {
		t.Fatalf("expected 0 active sessions initially, got %d", tracker.ActiveSessionCount())
	}

	// Add one agent
	tracker.HandleEvent(makeEvent(protocol.EventSessionStart, withAgent("agent-A", "sess-A")))
	if tracker.ActiveSessionCount() != 1 {
		t.Errorf("expected 1 active session, got %d", tracker.ActiveSessionCount())
	}

	// Add a second agent
	tracker.HandleEvent(makeEvent(protocol.EventSessionStart, withAgent("agent-B", "sess-B")))
	if tracker.ActiveSessionCount() != 2 {
		t.Errorf("expected 2 active sessions, got %d", tracker.ActiveSessionCount())
	}

	// End one session -> should exclude offline
	tracker.HandleEvent(makeEvent(protocol.EventSessionEnd, withAgent("agent-A", "sess-A")))
	if tracker.ActiveSessionCount() != 1 {
		t.Errorf("expected 1 active session after one ended, got %d", tracker.ActiveSessionCount())
	}

	// End the other
	tracker.HandleEvent(makeEvent(protocol.EventSessionEnd, withAgent("agent-B", "sess-B")))
	if tracker.ActiveSessionCount() != 0 {
		t.Errorf("expected 0 active sessions after all ended, got %d", tracker.ActiveSessionCount())
	}
}

func TestMultipleAgents(t *testing.T) {
	tracker := NewAgentTracker()

	// Start two different agents with different CLIs
	tracker.HandleEvent(makeEvent(protocol.EventSessionStart,
		withAgent("claude-main", "sess-c1"),
		withCLI(protocol.CLIClaude),
	))
	tracker.HandleEvent(makeEvent(protocol.EventSessionStart,
		withAgent("codex-main", "sess-x1"),
		withCLI(protocol.CLICodex),
	))

	agents := tracker.Agents()
	if len(agents) != 2 {
		t.Fatalf("expected 2 agents, got %d", len(agents))
	}

	// Build a lookup for easy assertion
	byID := make(map[string]protocol.AgentState, len(agents))
	for _, a := range agents {
		byID[a.ID] = a
	}

	claude, ok := byID["claude-main"]
	if !ok {
		t.Fatal("agent 'claude-main' not found")
	}
	if claude.CLIType != protocol.CLIClaude {
		t.Errorf("claude agent: expected CLI %q, got %q", protocol.CLIClaude, claude.CLIType)
	}
	if claude.Status != protocol.StatusActive {
		t.Errorf("claude agent: expected status %q, got %q", protocol.StatusActive, claude.Status)
	}

	codex, ok := byID["codex-main"]
	if !ok {
		t.Fatal("agent 'codex-main' not found")
	}
	if codex.CLIType != protocol.CLICodex {
		t.Errorf("codex agent: expected CLI %q, got %q", protocol.CLICodex, codex.CLIType)
	}

	// Put Claude in thinking, Codex starts a tool
	tracker.HandleEvent(makeEvent(protocol.EventThinking,
		withAgent("claude-main", "sess-c1"),
	))
	tracker.HandleEvent(makeEvent(protocol.EventToolStart,
		withAgent("codex-main", "sess-x1"),
		withTool("Bash", "npm test"),
	))

	agents = tracker.Agents()
	byID = make(map[string]protocol.AgentState, len(agents))
	for _, a := range agents {
		byID[a.ID] = a
	}

	claude = byID["claude-main"]
	if claude.Status != protocol.StatusThinking {
		t.Errorf("claude agent: expected status %q, got %q", protocol.StatusThinking, claude.Status)
	}

	codex = byID["codex-main"]
	if codex.Status != protocol.StatusTyping {
		t.Errorf("codex agent: expected status %q for Bash tool, got %q", protocol.StatusTyping, codex.Status)
	}
	if codex.CurrentTool != "Bash" {
		t.Errorf("codex agent: expected CurrentTool 'Bash', got %q", codex.CurrentTool)
	}

	// End Claude session, Codex should remain active
	tracker.HandleEvent(makeEvent(protocol.EventSessionEnd,
		withAgent("claude-main", "sess-c1"),
	))

	if tracker.ActiveSessionCount() != 1 {
		t.Errorf("expected 1 active session after claude ended, got %d", tracker.ActiveSessionCount())
	}

	agents = tracker.Agents()
	byID = make(map[string]protocol.AgentState, len(agents))
	for _, a := range agents {
		byID[a.ID] = a
	}

	claude = byID["claude-main"]
	if claude.Status != protocol.StatusOffline {
		t.Errorf("claude agent: expected status %q after session_end, got %q", protocol.StatusOffline, claude.Status)
	}

	codex = byID["codex-main"]
	if codex.Status != protocol.StatusTyping {
		t.Errorf("codex agent: expected status %q unchanged, got %q", protocol.StatusTyping, codex.Status)
	}

	// Verify total events: 2 starts + 1 thinking + 1 tool_start + 1 session_end = 5
	if tracker.TotalEvents() != 5 {
		t.Errorf("expected 5 total events, got %d", tracker.TotalEvents())
	}
}

// TestAgentAutoCreateOnFirstEvent verifies that an agent is auto-created
// on the first event even if it's not a session_start.
func TestAgentAutoCreateOnFirstEvent(t *testing.T) {
	tracker := NewAgentTracker()

	// Send a thinking event without a preceding session_start
	tracker.HandleEvent(makeEvent(protocol.EventThinking))

	agents := tracker.Agents()
	if len(agents) != 1 {
		t.Fatalf("expected 1 agent auto-created, got %d", len(agents))
	}
	// The auto-created agent starts as Active, then the thinking event sets it to Thinking
	if agents[0].Status != protocol.StatusThinking {
		t.Errorf("expected status %q, got %q", protocol.StatusThinking, agents[0].Status)
	}
}

// TestAgentIDFallback verifies the fallback ID generation when AgentID is empty.
func TestAgentIDFallback(t *testing.T) {
	tracker := NewAgentTracker()

	evt := protocol.AgentEvent{
		CLIType:   protocol.CLIGemini,
		SessionID: "sess-gemini-42",
		AgentID:   "", // empty -> should fallback
		Timestamp: time.Now(),
		EventType: protocol.EventSessionStart,
	}
	tracker.HandleEvent(evt)

	agents := tracker.Agents()
	if len(agents) != 1 {
		t.Fatalf("expected 1 agent, got %d", len(agents))
	}
	expectedID := "gemini-sess-gemini-42"
	if agents[0].ID != expectedID {
		t.Errorf("expected fallback ID %q, got %q", expectedID, agents[0].ID)
	}
}

// TestDisplayName verifies the display name generation.
func TestDisplayName(t *testing.T) {
	tests := []struct {
		cli       protocol.CLIType
		sessionID string
		want      string
	}{
		{protocol.CLIClaude, "abcdefghijklmnop", "claude-mnop"},
		{protocol.CLICodex, "short", "codex-hort"},
		{protocol.CLIGemini, "12345678", "gemini-5678"},
		{protocol.CLIClaude, "", "claude-"},
	}

	for _, tt := range tests {
		got := displayName(tt.cli, tt.sessionID)
		if got != tt.want {
			t.Errorf("displayName(%q, %q) = %q, want %q", tt.cli, tt.sessionID, got, tt.want)
		}
	}
}

// TestIsWriteTool verifies the write-tool classification.
func TestIsWriteTool(t *testing.T) {
	tests := []struct {
		toolName string
		want     bool
	}{
		{"Write", true},
		{"write", true},
		{"Edit", true},
		{"edit", true},
		{"Bash", true},
		{"bash", true},
		{"BASH", true},
		{"Read", false},
		{"Grep", false},
		{"Glob", false},
		{"ListFiles", false},
		{"", false},
	}

	for _, tt := range tests {
		got := isWriteTool(tt.toolName)
		if got != tt.want {
			t.Errorf("isWriteTool(%q) = %v, want %v", tt.toolName, got, tt.want)
		}
	}
}
