package core

// Layer 2: 資料流測試 — echo_guard
// 測「多函數串起來」的場景：
// - 混合多種 echo 類型的完整 strip 流程
// - strip 後再傳入 LooksLikeSystemEcho 驗證清潔度
// - 實際 Claude hook payload 格式混雜

import (
	"strings"
	"testing"
)

// TestEchoGuardDataflow_MixedEchoTypes verifies that a real-world payload
// containing RALPH LOOP + AUTOPILOT + system-reminder blocks all get stripped,
// while the genuine user instruction survives untouched.
func TestEchoGuardDataflow_MixedEchoTypes(t *testing.T) {
	input := `[RALPH LOOP - ITERATION 3]
Task: Fix the auth middleware
When FULLY complete run /oh-my-claudecode:cancel

[AUTOPILOT - mode active] continuing task

<system-reminder>
hook bash_safety: Success
hook secret_scan: Success
hook anvil_telemetry: Success
</system-reminder>

請繼續上一個任務，把 edge_ops 邏輯抽出來。`

	// Phase 1: detection
	if !LooksLikeSystemEcho(input) {
		t.Error("mixed echo input should be detected as echo")
	}

	// Phase 2: strip
	stripped := StripSystemEchoes(input)

	// All three echo block types must be gone.
	for _, fragment := range []string{
		"RALPH LOOP",
		"AUTOPILOT",
		"<system-reminder>",
		"hook bash_safety: Success",
	} {
		if strings.Contains(stripped, fragment) {
			t.Errorf("echo fragment %q still present after strip", fragment)
		}
	}

	// User instruction must survive.
	if !strings.Contains(stripped, "請繼續上一個任務") {
		t.Errorf("user content was lost in strip: %q", stripped)
	}

	// Phase 3: re-detect on stripped text — should now be clean.
	if LooksLikeSystemEcho(stripped) {
		t.Errorf("stripped text still detected as echo: %q", stripped)
	}
}

// TestEchoGuardDataflow_ConsecutiveSuccessLinesInMiddle verifies that when
// 3+ success lines appear in the middle of real user content, only the echo
// lines are removed and surrounding content is preserved.
func TestEchoGuardDataflow_ConsecutiveSuccessLinesInMiddle(t *testing.T) {
	input := `少爺你好，請幫我做以下事項：
hook bash_safety: Success
hook secret_scan: Success
hook anvil_telemetry: Success
幫我重構 memvault 的 kg_routes.py`

	if !LooksLikeSystemEcho(input) {
		t.Error("should detect echo when 3+ success lines present")
	}

	stripped := StripSystemEchoes(input)

	// Success lines should be stripped (or entire block neutralised).
	// User content on both sides must survive.
	if !strings.Contains(stripped, "少爺你好") {
		t.Error("content before success block lost after strip")
	}
	if !strings.Contains(stripped, "重構 memvault") {
		t.Error("content after success block lost after strip")
	}
}

// TestEchoGuardDataflow_StripThenLooksClean verifies the full pipeline:
// detect → strip → verify clean. This is the exact contract callers rely on.
func TestEchoGuardDataflow_StripThenLooksClean(t *testing.T) {
	cases := []string{
		"<system-reminder>\nhook a: Success\nhook b: Success\nhook c: Success\n</system-reminder>\n繼續。",
		"[RALPH LOOP - ITERATION 1]\nTask: rebuild\n繼續。",
		"[AUTOPILOT - mode active] continue\n繼續。",
	}

	for _, input := range cases {
		stripped := StripSystemEchoes(input)
		if LooksLikeSystemEcho(stripped) {
			t.Errorf("stripped text should not look like echo anymore:\ninput:   %q\nstripped: %q", input, stripped)
		}
	}
}

// TestEchoGuardDataflow_NoLeakOfEchoContent verifies that none of the
// canonical echo markers appear in stripped output, even when the block
// contains multi-line content.
func TestEchoGuardDataflow_NoLeakOfEchoContent(t *testing.T) {
	// A realistic Claude hook payload with <system-reminder> that contains
	// structured JSON-like content (edge case: could confuse naive parsers).
	input := `<system-reminder>
hook bash_safety: Success
hook secret_scan: Success
hook anvil_telemetry: Success
{"session_id":"abc","trigger":"auto"}
</system-reminder>
工作已完成，請繼續下一步。`

	stripped := StripSystemEchoes(input)

	leakMarkers := []string{
		"<system-reminder>",
		"</system-reminder>",
		"hook bash_safety",
		"hook secret_scan",
		"hook anvil_telemetry",
	}
	for _, m := range leakMarkers {
		if strings.Contains(stripped, m) {
			t.Errorf("echo content leaked into stripped output: %q found in %q", m, stripped)
		}
	}

	// User content must survive.
	if !strings.Contains(stripped, "工作已完成") {
		t.Error("user content after system-reminder block was lost")
	}
}
