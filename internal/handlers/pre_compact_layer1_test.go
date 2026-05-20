package handlers

// Layer 1: Unit test edge-case補強
// 測 pre_compact_test.go 未覆蓋的情境：
// - transcript_path 欄位不影響 checkpoint 寫入
// - session_id 含路徑分隔符 / 或 .. (path traversal guard)
// - checkpoint 目錄不存在時自動建立 (MkdirAll)
// - CreatedAt 必須是合法 RFC 3339 時間字串

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// TestPcWriteCheckpoint_WithTranscriptPath verifies that the transcript_path
// field in the payload does not break checkpoint writing (the field is captured
// in the payload but not stored in the checkpoint by contract).
func TestPcWriteCheckpoint_WithTranscriptPath(t *testing.T) {
	home, cleanup := setupPreCompactHome(t)
	defer cleanup()

	payload := PreCompactPayload{
		SessionID:      "sess-transcript",
		Trigger:        "auto",
		Cwd:            "/tmp/work",
		TranscriptPath: "/tmp/transcript-abc.jsonl",
	}

	if err := pcWriteCheckpoint(payload); err != nil {
		t.Fatalf("pcWriteCheckpoint with transcript_path: %v", err)
	}

	cp, ok := readCheckpoint(t, home, "sess-transcript")
	if !ok {
		t.Fatal("checkpoint file not found")
	}
	if cp.SessionID != "sess-transcript" {
		t.Errorf("SessionID mismatch: got %q", cp.SessionID)
	}
}

// TestPcWriteCheckpoint_CreatedAtIsValidRFC3339 verifies that the CreatedAt
// field set by pcWriteCheckpoint is a parseable RFC 3339 timestamp.
func TestPcWriteCheckpoint_CreatedAtIsValidRFC3339(t *testing.T) {
	home, cleanup := setupPreCompactHome(t)
	defer cleanup()

	payload := PreCompactPayload{SessionID: "sess-ts", Trigger: "auto"}
	if err := pcWriteCheckpoint(payload); err != nil {
		t.Fatalf("pcWriteCheckpoint: %v", err)
	}

	cp, ok := readCheckpoint(t, home, "sess-ts")
	if !ok {
		t.Fatal("checkpoint file not found")
	}

	_, err := time.Parse(time.RFC3339, cp.CreatedAt)
	if err != nil {
		// Also try RFC3339Nano which is a superset.
		_, err2 := time.Parse(time.RFC3339Nano, cp.CreatedAt)
		if err2 != nil {
			t.Errorf("CreatedAt %q is not valid RFC 3339: %v", cp.CreatedAt, err)
		}
	}
}

// TestPcWriteCheckpoint_AutoCreateDirectory verifies that when
// ~/.claude/data/pre-compact/ does not yet exist, pcWriteCheckpoint creates
// the full directory tree rather than returning an error.
func TestPcWriteCheckpoint_AutoCreateDirectory(t *testing.T) {
	home, cleanup := setupPreCompactHome(t)
	defer cleanup()

	// Explicitly ensure the target directory does NOT pre-exist.
	dir := filepath.Join(home, ".claude", "data", "pre-compact")
	os.RemoveAll(dir)

	payload := PreCompactPayload{SessionID: "sess-mkdir", Trigger: "auto"}
	if err := pcWriteCheckpoint(payload); err != nil {
		t.Fatalf("expected auto directory creation, got error: %v", err)
	}

	if _, statErr := os.Stat(dir); os.IsNotExist(statErr) {
		t.Error("directory was not created by pcWriteCheckpoint")
	}
}

// TestPcWriteCheckpoint_PathTraversalInSessionID verifies that a session_id
// containing path separators does not escape the pre-compact directory.
// The implementation should sanitise or reject such values.
func TestPcWriteCheckpoint_PathTraversalInSessionID(t *testing.T) {
	home, cleanup := setupPreCompactHome(t)
	defer cleanup()

	dangerousID := "../../../etc/evil"
	payload := PreCompactPayload{SessionID: dangerousID, Trigger: "auto"}

	err := pcWriteCheckpoint(payload)
	if err != nil {
		// Rejecting the write is acceptable behaviour.
		t.Logf("pcWriteCheckpoint rejected traversal ID (acceptable): %v", err)
		return
	}

	// If it did not error, verify the file was NOT written outside the
	// pre-compact directory.
	preCompactDir := filepath.Join(home, ".claude", "data", "pre-compact")
	entries, readErr := os.ReadDir(preCompactDir)
	if readErr != nil {
		t.Fatalf("could not read pre-compact dir: %v", readErr)
	}

	for _, e := range entries {
		if strings.Contains(e.Name(), "..") {
			t.Errorf("traversal sequence found in written filename: %q", e.Name())
		}
	}

	// The dangerous path must not exist outside pre-compact dir.
	escaped := filepath.Join(home, ".claude", "data", "etc", "evil.json")
	if _, statErr := os.Stat(escaped); statErr == nil {
		t.Errorf("path traversal succeeded — file exists at %q", escaped)
	}
}

// TestPreCompactHandle_TriggerPreservedInCheckpoint verifies that the trigger
// field ("auto" vs "manual") is round-tripped correctly through the handler.
func TestPreCompactHandle_TriggerPreservedInCheckpoint(t *testing.T) {
	home, cleanup := setupPreCompactHome(t)
	defer cleanup()

	for _, trigger := range []string{"auto", "manual"} {
		payload := PreCompactPayload{
			SessionID: "sess-trigger-" + trigger,
			Trigger:   trigger,
			Cwd:       "/tmp",
		}
		if err := pcWriteCheckpoint(payload); err != nil {
			t.Fatalf("write trigger=%s: %v", trigger, err)
		}
		cp, ok := readCheckpoint(t, home, "sess-trigger-"+trigger)
		if !ok {
			t.Fatalf("checkpoint not found for trigger=%s", trigger)
		}
		if cp.Trigger != trigger {
			t.Errorf("trigger mismatch: got %q want %q", cp.Trigger, trigger)
		}
	}
}

// TestPcWriteCheckpoint_JSONSchema verifies that the written file is valid JSON
// containing exactly the expected top-level keys.
func TestPcWriteCheckpoint_JSONSchema(t *testing.T) {
	home, cleanup := setupPreCompactHome(t)
	defer cleanup()

	payload := PreCompactPayload{SessionID: "sess-schema", Trigger: "auto", Cwd: "/work"}
	if err := pcWriteCheckpoint(payload); err != nil {
		t.Fatalf("pcWriteCheckpoint: %v", err)
	}

	path := filepath.Join(home, ".claude", "data", "pre-compact", "sess-schema.json")
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read checkpoint file: %v", err)
	}

	var generic map[string]any
	if err := json.Unmarshal(raw, &generic); err != nil {
		t.Fatalf("checkpoint is not valid JSON: %v\nraw: %s", err, raw)
	}

	required := []string{"session_id", "trigger", "cwd", "created_at"}
	for _, key := range required {
		if _, ok := generic[key]; !ok {
			t.Errorf("checkpoint JSON missing key %q", key)
		}
	}
}
