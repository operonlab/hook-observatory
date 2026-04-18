package handlers

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestInstinctDistillerSessionEnd_NoTranscript — missing transcript_path returns Allow
func TestInstinctDistillerSessionEnd_NoTranscript(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("HOME", dir)

	res := instinctDistillerHandle("SessionEnd", "", nil, `{"session_id":"s1"}`)
	if res.Decision != "" || res.Message != "" {
		t.Fatalf("expected allow with no transcript, got decision=%q message=%q", res.Decision, res.Message)
	}
}

// TestInstinctDistillerSessionEnd_NonExistentTranscript — transcript path does not exist → Allow
func TestInstinctDistillerSessionEnd_NonExistentTranscript(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("HOME", dir)

	raw := `{"session_id":"s1","transcript_path":"/nonexistent/path.jsonl"}`
	res := instinctDistillerHandle("SessionEnd", "", nil, raw)
	if res.Decision != "" {
		t.Fatalf("expected allow for missing transcript, got %q", res.Decision)
	}
}

// TestInstinctDistillerSessionEnd_ValidTranscript — valid transcript triggers background (non-blocking)
func TestInstinctDistillerSessionEnd_ValidTranscript(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("HOME", dir)

	// Create a dummy transcript file
	transcriptFile := filepath.Join(dir, "transcript.jsonl")
	os.WriteFile(transcriptFile, []byte(`{"type":"human","content":"hello"}`+"\n"), 0o644)

	raw, _ := json.Marshal(map[string]any{
		"session_id":      "sess-xyz",
		"transcript_path": transcriptFile,
	})
	res := instinctDistillerHandle("SessionEnd", "", nil, string(raw))
	// Must return allow (background fired or failed silently)
	if res.Decision != "" {
		t.Fatalf("expected allow, got %q", res.Decision)
	}
}

// TestInstinctDistillerSessionStart_NoPending — no pending.jsonl → Allow
func TestInstinctDistillerSessionStart_NoPending(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("HOME", dir)

	res := instinctDistillerHandle("SessionStart", "", nil, "")
	if res.Decision != "" || res.Message != "" {
		t.Fatalf("expected allow with no pending file, got decision=%q message=%q", res.Decision, res.Message)
	}
}

// writeInstinctPending writes a pending.jsonl to the actual idStagingDir()
// path (because core.Cfg() singleton already resolved paths and won't pick up
// t.Setenv changes). Returns a cleanup callback that restores any prior file.
func writeInstinctPending(t *testing.T, entries []map[string]any) {
	t.Helper()
	dir := idStagingDir()
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	pendingFile := filepath.Join(dir, "pending.jsonl")

	// Back up any existing pending.jsonl
	backup, _ := os.ReadFile(pendingFile)
	hadExisting := backup != nil

	var lines []string
	for _, e := range entries {
		b, _ := json.Marshal(e)
		lines = append(lines, string(b))
	}
	if err := os.WriteFile(pendingFile, []byte(strings.Join(lines, "\n")+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if hadExisting {
			_ = os.WriteFile(pendingFile, backup, 0o644)
		} else {
			_ = os.Remove(pendingFile)
		}
	})
}

// TestInstinctDistillerSessionStart_WithPending — unreviewed pending instincts → Message
func TestInstinctDistillerSessionStart_WithPending(t *testing.T) {
	writeInstinctPending(t, []map[string]any{
		{"skill_name": "my-skill", "signal_type": "retry", "summary": "let me retry", "reviewed": false},
		{"skill_name": "other-skill", "signal_type": "failure", "summary": "that didn't work", "reviewed": false},
		{"skill_name": "my-skill", "signal_type": "correction", "summary": "no not that", "reviewed": false},
	})

	res := instinctDistillerHandle("SessionStart", "", nil, "")
	if res.Message == "" {
		t.Fatalf("expected message with pending instincts, got empty message")
	}
	if !strings.Contains(res.Message, "Instinct 候選待審") {
		t.Errorf("expected header in message, got %q", res.Message)
	}
}

// TestInstinctDistillerSessionStart_OnlyReviewed — all reviewed entries → Allow
func TestInstinctDistillerSessionStart_OnlyReviewed(t *testing.T) {
	writeInstinctPending(t, []map[string]any{
		{"skill_name": "done-skill", "reviewed": true},
	})

	res := instinctDistillerHandle("SessionStart", "", nil, "")
	if res.Message != "" {
		t.Fatalf("expected no message for reviewed-only entries, got %q", res.Message)
	}
}

// TestInstinctDistillerUnknownEvent — unknown event → Allow
func TestInstinctDistillerUnknownEvent(t *testing.T) {
	res := instinctDistillerHandle("PreToolUse", "Bash", nil, `{}`)
	if res.Decision != "" || res.Message != "" {
		t.Fatalf("expected allow for unknown event, got decision=%q message=%q", res.Decision, res.Message)
	}
}

// TestInstinctDistillerSessionEnd_EmptyInput — empty raw_input → Allow
func TestInstinctDistillerSessionEnd_EmptyInput(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("HOME", dir)

	res := instinctDistillerHandle("SessionEnd", "", nil, "")
	if res.Decision != "" {
		t.Fatalf("expected allow for empty input, got %q", res.Decision)
	}
}
