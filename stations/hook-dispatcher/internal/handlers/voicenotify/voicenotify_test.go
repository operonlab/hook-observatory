package voicenotify

import (
	"strings"
	"testing"
)

func TestIsIntermediateChinese(t *testing.T) {
	cases := map[string]bool{
		"接下來我會處理這個":        true,
		"好的，我先來看看":          true,
		"讓我繼續處理":             true,
		"您希望我怎麼做？":          true,
		"請選擇":                  true,
		"任務已全部完成":            false,
		"測試通過":                 false,
	}
	for msg, want := range cases {
		if got := IsIntermediate(msg); got != want {
			t.Errorf("IsIntermediate(%q)=%v want %v", msg, got, want)
		}
	}
}

func TestIsIntermediateEnglish(t *testing.T) {
	cases := map[string]bool{
		"Let me continue with the next step":           true,
		"I'll now run the tests":                       true,
		"starting with the config file":                true,
		"Alright, moving on to the database":           true,
		"All tests passed. Done.":                      false,
		"Job complete.":                                false,
	}
	for msg, want := range cases {
		if got := IsIntermediate(msg); got != want {
			t.Errorf("IsIntermediate(%q)=%v want %v", msg, got, want)
		}
	}
}

func TestIsIntermediateQuestionTail(t *testing.T) {
	if !IsIntermediate("Does this approach work for you?") {
		t.Fatal("trailing ? must be detected as intermediate")
	}
	if IsIntermediate("The answer was 42.") {
		t.Fatal("declarative sentence must not match")
	}
	if IsIntermediate("") {
		t.Fatal("empty string must not match")
	}
}

func TestIsIntermediateTailOnly(t *testing.T) {
	// Pattern should only match the LAST 300 characters.
	prefix := strings.Repeat("完成任務。", 100) // 500+ chars of "done" text
	if IsIntermediate(prefix) {
		t.Fatal("tail-only scan should not match body containing no intermediate signal")
	}
	// Add intermediate signal at tail
	withTail := prefix + "接下來我會再檢查"
	if !IsIntermediate(withTail) {
		t.Fatal("intermediate signal at tail must match")
	}
}

func TestGetIdentPriority(t *testing.T) {
	t.Setenv("TMUX_PANE", "%42")
	if got := GetIdent("session-xyz"); got != "%42" {
		t.Fatalf("TMUX_PANE must win: got %q", got)
	}
	t.Setenv("TMUX_PANE", "")
	if got := GetIdent("session-xyz"); got != "session-xyz" {
		t.Fatalf("session_id fallback: got %q", got)
	}
	if got := GetIdent(""); !strings.HasPrefix(got, "pid-") {
		t.Fatalf("ppid fallback: got %q", got)
	}
}

func TestBuildStopMessageDefault(t *testing.T) {
	t.Setenv("TMUX_PANE", "")
	t.Setenv("CLAUDE_LABEL", "")
	msg := BuildStopMessage()
	if msg == "" || !strings.Contains(msg, "任務完成") {
		t.Fatalf("expected '任務完成' message, got %q", msg)
	}
}

func TestBuildStopMessageWithLabel(t *testing.T) {
	t.Setenv("TMUX_PANE", "")
	t.Setenv("CLAUDE_LABEL", "auth-refactor")
	msg := BuildStopMessage()
	if !strings.Contains(msg, "auth-refactor") {
		t.Fatalf("label must be injected: got %q", msg)
	}
}

func TestTeammateTypesContainsCommon(t *testing.T) {
	for _, k := range []string{"Plan", "worker", "general-purpose"} {
		if !TeammateTypes[k] {
			t.Errorf("expected teammate type %q", k)
		}
	}
	if TeammateTypes["not-a-teammate"] {
		t.Error("unknown type must not be flagged as teammate")
	}
}

func TestCheckerPIDPathStripsPercent(t *testing.T) {
	got := checkerPIDPath("%42")
	if got != "/tmp/tts-checker-42.pid" {
		t.Fatalf("unexpected checker pid path: %s", got)
	}
}

func TestCnNumeralDigitRange(t *testing.T) {
	if cnNumeral("3") != "三" {
		t.Error("3 → 三")
	}
	if cnNumeral("9") != "九" {
		t.Error("9 → 九")
	}
	// Out-of-range → passthrough
	if cnNumeral("42") != "42" {
		t.Error("two-digit passthrough failed")
	}
	if cnNumeral("abc") != "abc" {
		t.Error("non-numeric passthrough failed")
	}
}

func TestIsWordCharCJK(t *testing.T) {
	if !isWordChar('好') {
		t.Error("CJK char must be word-like")
	}
	if isWordChar(' ') {
		t.Error("space must not be word")
	}
	if !isWordChar('_') {
		t.Error("underscore must be word")
	}
}
