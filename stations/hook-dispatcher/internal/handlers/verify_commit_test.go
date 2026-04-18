package handlers

import (
	"os"
	"strings"
	"testing"
)

func TestVerifyCommitNonBash(t *testing.T) {
	// Edge: non-Bash tool → allow
	res := verifyCommitHandle("PreToolUse", "Write", map[string]any{"command": "git commit -m 'test'"}, "")
	if res.IsBlock() {
		t.Errorf("non-Bash tool should allow, got block: %q", res.Reason)
	}
}

func TestVerifyCommitNonCommit(t *testing.T) {
	// Happy path: Bash command that doesn't touch git commit → allow
	res := verifyCommitHandle("PreToolUse", "Bash", map[string]any{"command": "ls -la"}, "")
	if res.IsBlock() {
		t.Errorf("non-commit command should allow, got block: %q", res.Reason)
	}
}

func TestVerifyCommitTouchMarkerInCommand(t *testing.T) {
	// Command contains `touch /tmp/.claude-verified` → approve (marker creation pattern)
	cmd := "touch /tmp/.claude-verified && git commit -m 'verified'"
	res := verifyCommitHandle("PreToolUse", "Bash", map[string]any{"command": cmd}, "")
	if !res.IsApprove() {
		t.Errorf("touch-marker command should approve, got decision=%q", res.Decision)
	}
}

func TestVerifyCommitMarkerPresent(t *testing.T) {
	// Create marker → should approve and consume
	f, err := os.CreateTemp("", ".claude-verified-*")
	if err != nil {
		t.Fatal(err)
	}
	f.Close()
	markerPath := f.Name()
	defer os.Remove(markerPath)

	// Temporarily swap the constant by using the real path
	// Since vcMarker is a package const (/tmp/.claude-verified), we test via real file
	if err := os.WriteFile(vcMarker, []byte{}, 0o644); err != nil {
		t.Skipf("cannot write to %s (likely read-only env): %v", vcMarker, err)
	}
	defer os.Remove(vcMarker)

	res := verifyCommitHandle("PreToolUse", "Bash", map[string]any{"command": "git commit -m 'msg'"}, "")
	if !res.IsApprove() {
		t.Errorf("marker present should approve, got decision=%q reason=%q", res.Decision, res.Reason)
	}
	// Marker should be consumed
	if _, err := os.Stat(vcMarker); err == nil {
		t.Error("marker should have been deleted after approval")
	}
}

func TestVerifyCommitNoMarkerBlocks(t *testing.T) {
	// Ensure marker does not exist
	os.Remove(vcMarker)

	res := verifyCommitHandle("PreToolUse", "Bash", map[string]any{"command": "git commit -m 'msg'"}, "")
	if !res.IsBlock() {
		t.Errorf("no marker should block, got decision=%q", res.Decision)
	}
	if !strings.Contains(res.Reason, "VERIFICATION GATE") {
		t.Errorf("expected VERIFICATION GATE in reason, got %q", res.Reason)
	}
}

func TestVerifyCommitGhPrCreate(t *testing.T) {
	// `gh pr create` also requires verification
	os.Remove(vcMarker)
	res := verifyCommitHandle("PreToolUse", "Bash", map[string]any{"command": "gh pr create --title 'test'"}, "")
	if !res.IsBlock() {
		t.Errorf("gh pr create without marker should block, got %q", res.Decision)
	}
}
