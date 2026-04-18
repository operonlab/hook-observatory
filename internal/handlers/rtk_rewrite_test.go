package handlers

import (
	"testing"
)

func TestRtkRewriteNonBash(t *testing.T) {
	// Edge: non-Bash tool → always allow
	res := rtkRewriteHandle("PreToolUse", "Write", map[string]any{"command": "ls -la"}, "")
	if res.IsBlock() || res.UpdatedInput != nil {
		t.Errorf("non-Bash tool should passthrough, got %+v", res)
	}
}

func TestRtkRewriteEmptyCommand(t *testing.T) {
	// Edge: empty command → allow
	res := rtkRewriteHandle("PreToolUse", "Bash", map[string]any{"command": ""}, "")
	if res.IsBlock() || res.UpdatedInput != nil {
		t.Errorf("empty command should allow, got %+v", res)
	}
}

func TestRtkRewriteAlreadyRtk(t *testing.T) {
	// Edge: command already starts with `rtk ` → allow (skip re-rewriting)
	res := rtkRewriteHandle("PreToolUse", "Bash", map[string]any{"command": "rtk ls -la"}, "")
	if res.IsBlock() || res.UpdatedInput != nil {
		t.Errorf("already-rtk command should allow, got %+v", res)
	}
}

func TestRtkRewriteNoRtkBinary(t *testing.T) {
	// Happy path: rtk binary not found → allow (fail-open)
	// GetTool("rtk") returns "" if not installed; test just verifies we allow
	res := rtkRewriteHandle("PreToolUse", "Bash", map[string]any{"command": "ls -la /tmp"}, "")
	// Result is either allow (no rtk) or UpdatedInput (rtk installed)
	// In both cases should NOT block
	if res.IsBlock() {
		t.Errorf("rtk_rewrite should never block, got: %q", res.Reason)
	}
}
