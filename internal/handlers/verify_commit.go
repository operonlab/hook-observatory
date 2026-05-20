package handlers

import (
	"os"
	"regexp"

	"github.com/joneshong/hook-observatory/internal/core"
)

func init() {
	core.Register("PreToolUse", core.Entry{
		Matcher:    "Bash",
		Handler:    verifyCommitHandle,
		Critical:   true,
		ModuleName: "verify_commit",
	})
}

const vcMarker = "/tmp/.claude-verified"

var (
	reCommitGate  = regexp.MustCompile(`(git commit|gh pr create)`)
	reTouchMarker = regexp.MustCompile(`touch\s+/tmp/\.claude-verified`)
)

// verifyCommitHandle is the Go port of handlers/verify_commit.py.
//
// Gates `git commit` and `gh pr create` commands with a marker file at
// /tmp/.claude-verified. Workflow: run tests → touch marker → commit succeeds.
func verifyCommitHandle(_, toolName string, toolInput map[string]any, _ string) core.HookResult {
	if toolName != "Bash" {
		return core.Allow()
	}

	command, _ := toolInput["command"].(string)
	if !reCommitGate.MatchString(command) {
		return core.Allow()
	}

	// Command itself creates the marker (e.g. `touch marker && git commit`)
	// Hook runs before execution so the file won't exist yet — treat as verified.
	if reTouchMarker.MatchString(command) {
		return core.Approve()
	}

	// Marker exists → approve and consume it
	if _, err := os.Stat(vcMarker); err == nil {
		_ = os.Remove(vcMarker) // fail-open: ignore remove error
		return core.Approve()
	}

	// No marker → block with instructions
	return core.Block(
		"⚠️ VERIFICATION GATE: commit/PR 前必須先驗證。\n" +
			"1. 執行測試、build、lint 等驗證命令\n" +
			"2. 確認全部通過\n" +
			"3. 執行: touch /tmp/.claude-verified\n" +
			"4. 重新嘗試 commit",
	)
}
