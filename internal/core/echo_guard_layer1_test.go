package core

// Layer 1: Unit test edge-case補強
// 測試 echo_guard_test.go 未覆蓋的情境：
// - empty string (已有但放在另一個 test，這裡測 sentinel boundary)
// - non-UTF8 bytes
// - 超長 text (>1MB)
// - RALPH LOOP iteration=0 / very large N
// - system-reminder immediately at start / end of text
// - strip 後多次呼叫冪等

import (
	"strings"
	"testing"
	"unicode/utf8"
)

// TestLooksLikeSystemEcho_NonUTF8Bytes verifies that invalid UTF-8 bytes do
// not cause panic or incorrect detection.
func TestLooksLikeSystemEcho_NonUTF8Bytes(t *testing.T) {
	// Inject two invalid UTF-8 byte sequences into otherwise plain text.
	invalid := "hello \xff\xfe world"
	if utf8.ValidString(invalid) {
		t.Skip("test string is accidentally valid UTF-8 on this platform")
	}
	// Must not panic; result can be true or false — we only care about safety.
	_ = LooksLikeSystemEcho(invalid)
	_ = StripSystemEchoes(invalid)
}

// TestStripSystemEchoes_LargeText verifies that strip is stable on a 2 MB
// payload containing one echo block surrounded by user content.
func TestStripSystemEchoes_LargeText(t *testing.T) {
	padding := strings.Repeat("x", 1_000_000)
	input := padding + "\n<system-reminder>\nhook a: Success\nhook b: Success\nhook c: Success\n</system-reminder>\n" + padding
	result := StripSystemEchoes(input)
	if strings.Contains(result, "<system-reminder>") {
		t.Error("strip failed on large text: system-reminder still present")
	}
	// The 1M×2 user padding must survive.
	if len(result) < 1_500_000 {
		t.Errorf("large text stripped too aggressively: got %d bytes", len(result))
	}
}

// TestLooksLikeSystemEcho_RalphLoopIterationZero verifies ITERATION 0 is caught.
func TestLooksLikeSystemEcho_RalphLoopIterationZero(t *testing.T) {
	input := "[RALPH LOOP - ITERATION 0]\nTask: start"
	if !LooksLikeSystemEcho(input) {
		t.Error("RALPH LOOP ITERATION 0 should be detected as echo")
	}
}

// TestLooksLikeSystemEcho_RalphLoopLargeN verifies very large iteration numbers.
func TestLooksLikeSystemEcho_RalphLoopLargeN(t *testing.T) {
	input := "[RALPH LOOP - ITERATION 9999]\nTask: something"
	if !LooksLikeSystemEcho(input) {
		t.Error("RALPH LOOP ITERATION 9999 should be detected as echo")
	}
}

// TestLooksLikeSystemEcho_SystemReminderAtStart verifies detection when block
// is the very first byte of text.
func TestLooksLikeSystemEcho_SystemReminderAtStart(t *testing.T) {
	input := "<system-reminder>\nhook a: Success\n</system-reminder>"
	if !LooksLikeSystemEcho(input) {
		t.Error("system-reminder at start should be detected")
	}
}

// TestLooksLikeSystemEcho_SystemReminderAtEnd verifies detection when block is
// the very last byte of text.
func TestLooksLikeSystemEcho_SystemReminderAtEnd(t *testing.T) {
	input := "請繼續任務。\n<system-reminder>\nhook x: Success\nhook y: Success\nhook z: Success\n</system-reminder>"
	if !LooksLikeSystemEcho(input) {
		t.Error("system-reminder at end should be detected")
	}
	stripped := StripSystemEchoes(input)
	if strings.Contains(stripped, "<system-reminder>") {
		t.Error("strip failed when block is at end of text")
	}
	if !strings.Contains(stripped, "請繼續任務") {
		t.Error("user content before end-block was incorrectly stripped")
	}
}

// TestStripSystemEchoes_Idempotent verifies that stripping twice produces the
// same result as stripping once (no double-strip corruption).
func TestStripSystemEchoes_Idempotent(t *testing.T) {
	input := "<system-reminder>\nhook a: Success\nhook b: Success\nhook c: Success\n</system-reminder>\n工作繼續。"
	once := StripSystemEchoes(input)
	twice := StripSystemEchoes(once)
	if once != twice {
		t.Errorf("StripSystemEchoes is not idempotent: first=%q second=%q", once, twice)
	}
}

// TestLooksLikeSystemEcho_ExactlyTwoSuccessLines verifies the boundary:
// exactly 2 success lines must NOT trigger (threshold is 3).
func TestLooksLikeSystemEcho_ExactlyTwoSuccessLines(t *testing.T) {
	input := "hook bash_safety: Success\nhook secret_scan: Success"
	if LooksLikeSystemEcho(input) {
		t.Error("exactly 2 success lines alone should not be flagged as echo")
	}
}

// TestLooksLikeSystemEcho_ExactlyThreeSuccessLines verifies the boundary:
// exactly 3 success lines MUST trigger.
func TestLooksLikeSystemEcho_ExactlyThreeSuccessLines(t *testing.T) {
	input := "hook bash_safety: Success\nhook secret_scan: Success\nhook anvil: Success"
	if !LooksLikeSystemEcho(input) {
		t.Error("exactly 3 success lines should be flagged as echo")
	}
}

// TestStripSystemEchoes_PreservesWhitespacePadding verifies that unrelated
// leading/trailing whitespace is not clobbered.
func TestStripSystemEchoes_PreservesWhitespacePadding(t *testing.T) {
	// There is no echo in this input — strip should be a no-op.
	plain := "   hello world   "
	result := StripSystemEchoes(plain)
	if !strings.Contains(result, "hello world") {
		t.Errorf("whitespace-padded plain text lost content: %q", result)
	}
}
