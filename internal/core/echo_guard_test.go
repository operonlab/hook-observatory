package core

import (
	"strings"
	"testing"
)

func TestLooksLikeSystemEcho_PlainText(t *testing.T) {
	plain := "請幫我重構 memvault 的 kg_routes.py，把 edge_ops 邏輯抽出來。"
	if LooksLikeSystemEcho(plain) {
		t.Errorf("plain text incorrectly flagged as echo: %q", plain)
	}
	result := StripSystemEchoes(plain)
	if result != plain {
		t.Errorf("StripSystemEchoes modified plain text: got %q, want %q", result, plain)
	}
}

func TestLooksLikeSystemEcho_SystemReminderBlock(t *testing.T) {
	input := `<system-reminder>
hook bash_safety: Success
hook secret_scan: Success
</system-reminder>
繼續上一個任務。`

	if !LooksLikeSystemEcho(input) {
		t.Error("expected system-reminder block to be detected as echo")
	}
	stripped := StripSystemEchoes(input)
	if strings.Contains(stripped, "<system-reminder>") {
		t.Errorf("system-reminder block not stripped: %q", stripped)
	}
	// Real user content should survive stripping
	if !strings.Contains(stripped, "繼續上一個任務") {
		t.Errorf("user content was stripped unexpectedly: %q", stripped)
	}
}

func TestLooksLikeSystemEcho_RalphLoopStyle(t *testing.T) {
	input := `[RALPH LOOP - ITERATION 3]
Task: Fix the auth middleware
When FULLY complete (after Architect verification)
run /oh-my-claudecode:cancel`

	if !LooksLikeSystemEcho(input) {
		t.Error("expected RALPH LOOP block to be detected as echo")
	}
	stripped := StripSystemEchoes(input)
	if strings.Contains(stripped, "RALPH LOOP") {
		t.Errorf("RALPH LOOP block not stripped: %q", stripped)
	}
}

func TestLooksLikeSystemEcho_AutopilotBlock(t *testing.T) {
	input := "[AUTOPILOT - mode active] continuing task"
	if !LooksLikeSystemEcho(input) {
		t.Error("expected AUTOPILOT block to be detected as echo")
	}
}

func TestLooksLikeSystemEcho_SuccessLines(t *testing.T) {
	// 3 success lines → heuristic triggers
	input := strings.Join([]string{
		"hook bash_safety: Success",
		"hook secret_scan: Success",
		"hook anvil_telemetry: Success",
	}, "\n")
	if !LooksLikeSystemEcho(input) {
		t.Error("expected 3+ success lines to be detected as echo")
	}

	// 2 success lines → should NOT trigger
	input2 := strings.Join([]string{
		"hook bash_safety: Success",
		"hook secret_scan: Success",
		"做這件事。",
	}, "\n")
	if LooksLikeSystemEcho(input2) {
		t.Error("2 success lines + real text should not be flagged as echo")
	}
}

func TestStripSystemEchoes_EmptyInput(t *testing.T) {
	if got := StripSystemEchoes(""); got != "" {
		t.Errorf("expected empty string, got %q", got)
	}
	if LooksLikeSystemEcho("") {
		t.Error("empty string should not be echo")
	}
}
