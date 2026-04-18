package handlers

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestUtilityWatchdogSessionEnd_NoSessionID — missing session_id returns Allow
func TestUtilityWatchdogSessionEnd_NoSessionID(t *testing.T) {
	res := utilityWatchdogHandle("SessionEnd", "", nil, `{}`)
	if res.Decision != "" || res.Message != "" {
		t.Fatalf("expected plain allow, got decision=%q message=%q", res.Decision, res.Message)
	}
}

// TestUtilityWatchdogSessionEnd_WithSessionID — valid session_id triggers background (non-blocking)
func TestUtilityWatchdogSessionEnd_WithSessionID(t *testing.T) {
	// We can't assert the background process ran (script may not exist in CI),
	// but the handler must return allow without panic.
	dir := t.TempDir()
	t.Setenv("HOME", dir)

	raw := `{"session_id":"test-session-abc"}`
	res := utilityWatchdogHandle("SessionEnd", "", nil, raw)
	if res.Decision != "" {
		t.Fatalf("expected allow (empty decision), got %q", res.Decision)
	}
}

// TestUtilityWatchdogSessionStart_NoProposals — empty data dir returns Allow
func TestUtilityWatchdogSessionStart_NoProposals(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("HOME", dir)

	res := utilityWatchdogHandle("SessionStart", "", nil, "")
	if res.Decision != "" || res.Message != "" {
		t.Fatalf("expected allow on empty dir, got decision=%q message=%q", res.Decision, res.Message)
	}
}

// TestUtilityWatchdogSessionStart_ProposalsBelowThreshold — fewer than 3 proposals → Allow
func TestUtilityWatchdogSessionStart_ProposalsBelowThreshold(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("HOME", dir)

	dataDir := filepath.Join(dir, ".claude", "data", "utility-watchdog")
	if err := os.MkdirAll(dataDir, 0o755); err != nil {
		t.Fatal(err)
	}

	// Write 2 proposals for the same skill (threshold is 3)
	proposalsFile := filepath.Join(dataDir, "proposals.jsonl")
	entry := map[string]any{"skill_name": "my-skill", "utility": 0.3}
	line, _ := json.Marshal(entry)
	content := string(line) + "\n" + string(line) + "\n"
	os.WriteFile(proposalsFile, []byte(content), 0o644)

	res := utilityWatchdogHandle("SessionStart", "", nil, "")
	if res.Message != "" {
		t.Fatalf("expected no message below threshold, got %q", res.Message)
	}
}

// TestUtilityWatchdogSessionStart_ProposalsAtThreshold — 3 proposals → Message
func TestUtilityWatchdogSessionStart_ProposalsAtThreshold(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("HOME", dir)

	dataDir := filepath.Join(dir, ".claude", "data", "utility-watchdog")
	if err := os.MkdirAll(dataDir, 0o755); err != nil {
		t.Fatal(err)
	}

	proposalsFile := filepath.Join(dataDir, "proposals.jsonl")
	entry := map[string]any{"skill_name": "low-skill", "utility": 0.1}
	line, _ := json.Marshal(entry)
	content := string(line) + "\n" + string(line) + "\n" + string(line) + "\n"
	os.WriteFile(proposalsFile, []byte(content), 0o644)

	res := utilityWatchdogHandle("SessionStart", "", nil, "")
	if res.Message == "" {
		t.Fatalf("expected message at threshold, got empty message (decision=%q)", res.Decision)
	}
	if !strings.Contains(res.Message, "low-skill") {
		t.Errorf("expected skill name in message body, got %q", res.Message)
	}
}

// TestUtilityWatchdogSessionStart_CreateProposals — 5 create-proposals → Message
func TestUtilityWatchdogSessionStart_CreateProposals(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("HOME", dir)

	dataDir := filepath.Join(dir, ".claude", "data", "utility-watchdog")
	if err := os.MkdirAll(dataDir, 0o755); err != nil {
		t.Fatal(err)
	}

	createFile := filepath.Join(dataDir, "create-proposals.jsonl")
	lines := strings.Repeat(`{"session":"x"}`+"\n", 5)
	os.WriteFile(createFile, []byte(lines), 0o644)

	res := utilityWatchdogHandle("SessionStart", "", nil, "")
	if res.Message == "" {
		t.Fatalf("expected message for create proposals, got empty message")
	}
	if !strings.Contains(res.Message, "CreateOnMiss") {
		t.Errorf("expected CreateOnMiss in message, got %q", res.Message)
	}
}

// TestUtilityWatchdogUnknownEvent — unknown event returns Allow
func TestUtilityWatchdogUnknownEvent(t *testing.T) {
	res := utilityWatchdogHandle("PreToolUse", "Bash", nil, `{}`)
	if res.Decision != "" || res.Message != "" {
		t.Fatalf("expected allow for unknown event, got decision=%q message=%q", res.Decision, res.Message)
	}
}

// TestUtilityWatchdogSessionStart_FileTooLarge — oversized file is truncated, returns Allow
func TestUtilityWatchdogSessionStart_FileTooLarge(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("HOME", dir)

	dataDir := filepath.Join(dir, ".claude", "data", "utility-watchdog")
	if err := os.MkdirAll(dataDir, 0o755); err != nil {
		t.Fatal(err)
	}

	proposalsFile := filepath.Join(dataDir, "proposals.jsonl")
	// Write > 100_000 bytes
	big := strings.Repeat(`{"skill_name":"x","utility":0.5}`+"\n", 4000)
	os.WriteFile(proposalsFile, []byte(big), 0o644)

	res := utilityWatchdogHandle("SessionStart", "", nil, "")
	// Should truncate the file and return Allow
	if res.Decision != "" || res.Message != "" {
		t.Fatalf("expected allow after truncation, got decision=%q message=%q", res.Decision, res.Message)
	}
	info, _ := os.Stat(proposalsFile)
	if info.Size() != 0 {
		t.Errorf("expected proposals file truncated to 0, got %d bytes", info.Size())
	}
}
