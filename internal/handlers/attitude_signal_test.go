package handlers

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func readLastCorrection(t *testing.T, home string) map[string]any {
	t.Helper()
	correctionsRoot := filepath.Join(home, "Claude", "memvault", "corrections", "auto")
	var lastFile string
	entries, _ := os.ReadDir(correctionsRoot)
	for _, e := range entries {
		if e.IsDir() {
			monthPath := filepath.Join(correctionsRoot, e.Name())
			files, _ := os.ReadDir(monthPath)
			for _, f := range files {
				lastFile = filepath.Join(monthPath, f.Name())
			}
		}
	}
	if lastFile == "" {
		return nil
	}
	raw, err := os.ReadFile(lastFile)
	if err != nil {
		return nil
	}
	lines := strings.Split(strings.TrimSpace(string(raw)), "\n")
	if len(lines) == 0 {
		return nil
	}
	var record map[string]any
	json.Unmarshal([]byte(lines[len(lines)-1]), &record)
	return record
}

// ---------------------------------------------------------------------------
// Notification tests
// ---------------------------------------------------------------------------

// TestAttitudeSignalNotification_NoDenial — notification without denial → Allow, no file written
func TestAttitudeSignalNotification_NoDenial(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("HOME", dir)

	raw := `{"message":"Tool completed successfully"}`
	res := attitudeSignalHandle("Notification", "Bash", nil, raw)
	if res.Decision != "" || res.Message != "" {
		t.Fatalf("expected allow, got decision=%q message=%q", res.Decision, res.Message)
	}
	if r := readLastCorrection(t, dir); r != nil {
		t.Errorf("expected no correction file written, found: %v", r)
	}
}

// TestAttitudeSignalNotification_WithDenied — "denied" in message → writes autonomy_level correction
func TestAttitudeSignalNotification_WithDenied(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("HOME", dir)

	raw, _ := json.Marshal(map[string]any{
		"message": "Tool denied by user",
		"data": map[string]any{
			"tool_name":  "Write",
			"session_id": "sess-001",
		},
	})
	res := attitudeSignalHandle("Notification", "Write", nil, string(raw))
	if res.Decision != "" {
		t.Fatalf("expected allow, got %q", res.Decision)
	}

	correction := readLastCorrection(t, dir)
	if correction == nil {
		t.Fatal("expected correction file to be written")
	}
	if correction["category"] != "autonomy_level" {
		t.Errorf("expected category=autonomy_level, got %v", correction["category"])
	}
}

// TestAttitudeSignalNotification_ToolDeniedType — type=tool_denied → writes correction
func TestAttitudeSignalNotification_ToolDeniedType(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("HOME", dir)

	raw, _ := json.Marshal(map[string]any{
		"message": "Notification from system",
		"data": map[string]any{
			"type":       "tool_denied",
			"tool_name":  "Edit",
			"session_id": "sess-002",
		},
	})
	res := attitudeSignalHandle("Notification", "", nil, string(raw))
	if res.Decision != "" {
		t.Fatalf("expected allow, got %q", res.Decision)
	}

	correction := readLastCorrection(t, dir)
	if correction == nil {
		t.Fatal("expected correction file to be written")
	}
	if correction["category"] != "autonomy_level" {
		t.Errorf("expected category=autonomy_level, got %v", correction["category"])
	}
}

// TestAttitudeSignalNotification_InvalidJSON — bad JSON → Allow (fail-open)
func TestAttitudeSignalNotification_InvalidJSON(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("HOME", dir)

	res := attitudeSignalHandle("Notification", "", nil, `{invalid json`)
	if res.Decision != "" {
		t.Fatalf("expected allow on bad JSON, got %q", res.Decision)
	}
}

// ---------------------------------------------------------------------------
// SessionEnd tests
// ---------------------------------------------------------------------------

// TestAttitudeSignalSessionEnd_NoSessionID — missing session_id → Allow
func TestAttitudeSignalSessionEnd_NoSessionID(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("HOME", dir)

	res := attitudeSignalHandle("SessionEnd", "", nil, `{}`)
	if res.Decision != "" {
		t.Fatalf("expected allow, got %q", res.Decision)
	}
}

// TestAttitudeSignalSessionEnd_NoSpoolFile — spool not present → Allow
func TestAttitudeSignalSessionEnd_NoSpoolFile(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("HOME", dir)

	raw := `{"session_id":"sess-xyz"}`
	res := attitudeSignalHandle("SessionEnd", "", nil, raw)
	if res.Decision != "" {
		t.Fatalf("expected allow without spool, got %q", res.Decision)
	}
}

// TestAttitudeSignalSessionEnd_HighDenyCount — 3+ denials → writes autonomy_level correction
func TestAttitudeSignalSessionEnd_HighDenyCount(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("HOME", dir)

	// Build spool file
	spoolDir := filepath.Join(dir, ".hook-observatory", "spool")
	os.MkdirAll(spoolDir, 0o755)
	spoolFile := filepath.Join(spoolDir, "events.jsonl")

	sessionID := "sess-deny"
	var spoolLines []string
	for i := 0; i < 3; i++ {
		evt := map[string]any{
			"event_type": "Notification",
			"ts":         "2026-01-01T00:00:00.000Z",
			"data": map[string]any{
				"session_id": sessionID,
				"message":    "Tool denied",
			},
		}
		b, _ := json.Marshal(evt)
		spoolLines = append(spoolLines, string(b))
	}
	os.WriteFile(spoolFile, []byte(strings.Join(spoolLines, "\n")+"\n"), 0o644)

	raw, _ := json.Marshal(map[string]any{"session_id": sessionID})
	res := attitudeSignalHandle("SessionEnd", "", nil, string(raw))
	if res.Decision != "" {
		t.Fatalf("expected allow, got %q", res.Decision)
	}

	correction := readLastCorrection(t, dir)
	if correction == nil {
		t.Fatal("expected autonomy_level correction to be written")
	}
	if correction["category"] != "autonomy_level" {
		t.Errorf("expected autonomy_level, got %v", correction["category"])
	}
}

// TestAttitudeSignalSessionEnd_HighToolDensity — tool_count/message_count > 15 → verbosity correction
func TestAttitudeSignalSessionEnd_HighToolDensity(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("HOME", dir)

	spoolDir := filepath.Join(dir, ".hook-observatory", "spool")
	os.MkdirAll(spoolDir, 0o755)
	spoolFile := filepath.Join(spoolDir, "events.jsonl")

	sessionID := "sess-density"
	var spoolLines []string

	// 1 UserPromptSubmit
	userEvt := map[string]any{
		"event_type": "UserPromptSubmit",
		"ts":         "2026-01-01T00:00:00.000Z",
		"data":       map[string]any{"session_id": sessionID},
	}
	b, _ := json.Marshal(userEvt)
	spoolLines = append(spoolLines, string(b))

	// 16 PreToolUse → ratio 16 > 15
	for i := 0; i < 16; i++ {
		toolEvt := map[string]any{
			"event_type": "PreToolUse",
			"ts":         "2026-01-01T00:00:00.000Z",
			"data":       map[string]any{"session_id": sessionID},
		}
		tb, _ := json.Marshal(toolEvt)
		spoolLines = append(spoolLines, string(tb))
	}
	os.WriteFile(spoolFile, []byte(strings.Join(spoolLines, "\n")+"\n"), 0o644)

	raw, _ := json.Marshal(map[string]any{"session_id": sessionID})
	res := attitudeSignalHandle("SessionEnd", "", nil, string(raw))
	if res.Decision != "" {
		t.Fatalf("expected allow, got %q", res.Decision)
	}

	correction := readLastCorrection(t, dir)
	if correction == nil {
		t.Fatal("expected verbosity correction to be written")
	}
	if correction["category"] != "verbosity" {
		t.Errorf("expected verbosity, got %v", correction["category"])
	}
}

// TestAttitudeSignalUnknownEvent — unknown event → Allow
func TestAttitudeSignalUnknownEvent(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("HOME", dir)

	res := attitudeSignalHandle("PreToolUse", "Bash", nil, `{}`)
	if res.Decision != "" || res.Message != "" {
		t.Fatalf("expected allow for unknown event, got decision=%q message=%q", res.Decision, res.Message)
	}
}
