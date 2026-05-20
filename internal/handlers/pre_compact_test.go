package handlers

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/joneshong/hook-observatory/internal/core"
)

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// setupPreCompactHome creates a temp home dir and overrides HOME for the test.
func setupPreCompactHome(t *testing.T) (home string, cleanup func()) {
	t.Helper()
	home = t.TempDir()
	origHome := os.Getenv("HOME")
	os.Setenv("HOME", home)
	cleanup = func() {
		os.Setenv("HOME", origHome)
	}
	return home, cleanup
}

// readCheckpoint reads the checkpoint JSON written by pcWriteCheckpoint.
func readCheckpoint(t *testing.T, home, sessionID string) (PreCompactCheckpoint, bool) {
	t.Helper()
	path := filepath.Join(home, ".claude", "data", "pre-compact", sessionID+".json")
	raw, err := os.ReadFile(path)
	if err != nil {
		return PreCompactCheckpoint{}, false
	}
	var cp PreCompactCheckpoint
	if err := json.Unmarshal(raw, &cp); err != nil {
		t.Fatalf("readCheckpoint: unmarshal: %v", err)
	}
	return cp, true
}

// ---------------------------------------------------------------------------
// pcWriteCheckpoint unit tests
// ---------------------------------------------------------------------------

// TestPcWriteCheckpoint_Basic verifies that a checkpoint is written correctly
// for a well-formed payload.
func TestPcWriteCheckpoint_Basic(t *testing.T) {
	home, cleanup := setupPreCompactHome(t)
	defer cleanup()

	payload := PreCompactPayload{
		SessionID: "test-session-001",
		Trigger:   "manual",
		Cwd:       "/Users/tester/workshop",
	}

	if err := pcWriteCheckpoint(payload); err != nil {
		t.Fatalf("pcWriteCheckpoint: unexpected error: %v", err)
	}

	cp, ok := readCheckpoint(t, home, "test-session-001")
	if !ok {
		t.Fatal("checkpoint file not found")
	}

	if cp.SessionID != "test-session-001" {
		t.Errorf("SessionID: got %q, want %q", cp.SessionID, "test-session-001")
	}
	if cp.Trigger != "manual" {
		t.Errorf("Trigger: got %q, want %q", cp.Trigger, "manual")
	}
	if cp.Cwd != "/Users/tester/workshop" {
		t.Errorf("Cwd: got %q, want %q", cp.Cwd, "/Users/tester/workshop")
	}
	if cp.CreatedAt == "" {
		t.Error("CreatedAt must not be empty")
	}
}

// TestPcWriteCheckpoint_EmptySessionID verifies that an "unknown" fallback is
// used when session_id is missing, and the file is still written.
func TestPcWriteCheckpoint_EmptySessionID(t *testing.T) {
	home, cleanup := setupPreCompactHome(t)
	defer cleanup()

	payload := PreCompactPayload{Trigger: "auto"}

	if err := pcWriteCheckpoint(payload); err != nil {
		t.Fatalf("pcWriteCheckpoint (empty session_id): unexpected error: %v", err)
	}

	_, ok := readCheckpoint(t, home, "unknown")
	if !ok {
		t.Fatal("checkpoint file not found for 'unknown' session_id")
	}
}

// TestPcWriteCheckpoint_Overwrite verifies that a second write with the same
// session_id overwrites the previous checkpoint (latest-wins semantics).
func TestPcWriteCheckpoint_Overwrite(t *testing.T) {
	home, cleanup := setupPreCompactHome(t)
	defer cleanup()

	p1 := PreCompactPayload{SessionID: "sess-overwrite", Trigger: "auto", Cwd: "/first"}
	p2 := PreCompactPayload{SessionID: "sess-overwrite", Trigger: "manual", Cwd: "/second"}

	if err := pcWriteCheckpoint(p1); err != nil {
		t.Fatalf("first write: %v", err)
	}
	if err := pcWriteCheckpoint(p2); err != nil {
		t.Fatalf("second write: %v", err)
	}

	cp, ok := readCheckpoint(t, home, "sess-overwrite")
	if !ok {
		t.Fatal("checkpoint file not found")
	}
	if cp.Cwd != "/second" {
		t.Errorf("overwrite: Cwd got %q, want %q", cp.Cwd, "/second")
	}
}

// ---------------------------------------------------------------------------
// preCompactHandle integration tests
// ---------------------------------------------------------------------------

// TestPreCompactHandle_WellFormedPayload verifies that the handler:
//   - does not crash
//   - writes a checkpoint file
//   - returns a non-empty hint message
func TestPreCompactHandle_WellFormedPayload(t *testing.T) {
	home, cleanup := setupPreCompactHome(t)
	defer cleanup()

	// Register fresh (avoid duplicate from package init; Reset clears registry).
	core.Reset()
	RegisterPreCompact()

	raw := `{"session_id":"integ-001","trigger":"auto","cwd":"/Users/tester/workshop"}`
	result := core.Dispatch("PreCompact", raw)

	// Dispatch returns JSON; message field must be present and non-empty.
	var out map[string]any
	if err := json.Unmarshal([]byte(result), &out); err != nil {
		t.Fatalf("output is not valid JSON: %v\nraw: %s", err, result)
	}

	msg, _ := out["message"].(string)
	if msg == "" {
		t.Errorf("expected non-empty message field in output, got: %s", result)
	}
	if !strings.Contains(msg, "PreCompact") {
		t.Errorf("message should contain 'PreCompact', got: %s", msg)
	}

	// Checkpoint must be on disk.
	_, ok := readCheckpoint(t, home, "integ-001")
	if !ok {
		t.Error("checkpoint file not found after dispatch")
	}
}

// TestPreCompactHandle_MalformedJSON verifies fail-open behaviour: a garbage
// payload must not crash the handler and must still return valid output.
func TestPreCompactHandle_MalformedJSON(t *testing.T) {
	_, cleanup := setupPreCompactHome(t)
	defer cleanup()

	core.Reset()
	RegisterPreCompact()

	result := core.Dispatch("PreCompact", "not-json-at-all")

	var out map[string]any
	if err := json.Unmarshal([]byte(result), &out); err != nil {
		t.Fatalf("malformed payload produced invalid JSON output: %v\nraw: %s", err, result)
	}
}

// TestPreCompactHandle_EmptyPayload verifies that an empty string payload is
// handled gracefully (session_id defaults to "unknown").
func TestPreCompactHandle_EmptyPayload(t *testing.T) {
	home, cleanup := setupPreCompactHome(t)
	defer cleanup()

	core.Reset()
	RegisterPreCompact()

	result := core.Dispatch("PreCompact", "")

	var out map[string]any
	if err := json.Unmarshal([]byte(result), &out); err != nil {
		t.Fatalf("empty payload produced invalid JSON output: %v\nraw: %s", err, result)
	}

	// "unknown" checkpoint should exist.
	_, ok := readCheckpoint(t, home, "unknown")
	if !ok {
		t.Error("checkpoint file not found for 'unknown' session_id")
	}
}
