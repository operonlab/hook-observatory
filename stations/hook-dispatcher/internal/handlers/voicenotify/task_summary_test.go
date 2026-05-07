package voicenotify

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// ---------------------------------------------------------------------------
// TaskSummaryFromPrompt — pipeline input/output contract
// ---------------------------------------------------------------------------

func TestTaskSummaryFromPrompt_StripsFillerPrefixes(t *testing.T) {
	cases := []struct {
		name string
		in   string
		want string
	}{
		{"幫我", "幫我修 emoji 過濾的 bug", "修 emoji 過濾的 bug"},
		{"我想", "我想加 UserPromptSubmit hook", "加 UserPromptSubmit hook"},
		{"你幫我", "你幫我看一下 SoundSource 為什麼壞掉", "看一下 SoundSource 為什麼壞掉"},
		{"麻煩你幫我", "麻煩你幫我重啟 coreaudiod 看看", "重啟 coreaudiod 看看"},
		{"能不能", "能不能幫我把預設語音換成曉曉", "把預設語音換成曉曉"},
		// longest-first ordering — "你幫我" should win over "幫我"
		{"longest-first", "你幫我看 issue 26", "看 issue 26"},
		// First-person action prefixes — strip subject so template
		// "少爺，{summary}的任務完成了" doesn't read like the assistant
		// is talking about itself ("少爺，我要... 任務完成了").
		{"我要", "我要修 ttsfat 的 bug", "修 ttsfat 的 bug"},
		{"我來", "我來看看 SoundSource", "看看 SoundSource"},
		{"我得", "我得處理 hook 重啟問題", "處理 hook 重啟問題"},
		{"我先", "我先 grep 一下相關 caller", "grep 一下相關 caller"},
		{"我該", "我該如何重啟 mcpproxy", "如何重啟 mcpproxy"},
		{"我去", "我去確認一下 launchctl", "確認一下 launchctl"},
		{"我必須", "我必須先處理 redis 連線", "先處理 redis 連線"},
		{"我打算", "我打算把 detect 拆成兩個檔", "把 detect 拆成兩個檔"},
		{"我準備", "我準備 push 到 main 看看", "push 到 main 看看"},
		{"我接下來", "我接下來要看 OAuth flow", "要看 OAuth flow"},
		// longest-first guard — "我想要" must win over "我想"
		{"longest-first 我想要", "我想要看一下 issue 26", "看一下 issue 26"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := TaskSummaryFromPrompt(tc.in)
			if got != tc.want {
				t.Errorf("\n  in=%q\n got=%q\nwant=%q", tc.in, got, tc.want)
			}
		})
	}
}

func TestTaskSummaryFromPrompt_StripsLeadingEmoji(t *testing.T) {
	cases := map[string]string{
		"✳ 修 emoji 過濾 bug":    "修 emoji 過濾 bug",
		"⚡relay 任務 dispatch":   "relay 任務 dispatch",
		"⠐ Claude Code 修 hook": "Claude Code 修 hook",
	}
	for in, want := range cases {
		got := TaskSummaryFromPrompt(in)
		if got != want {
			t.Errorf("\n  in=%q\n got=%q\nwant=%q", in, got, want)
		}
	}
}

func TestTaskSummaryFromPrompt_RejectsShortReplies(t *testing.T) {
	// All under 6 runes after trimming; should produce "" (skip-write signal).
	for _, in := range []string{"好", "對", "OK", "嗯", "繼續", "go", "✓"} {
		if got := TaskSummaryFromPrompt(in); got != "" {
			t.Errorf("short reply %q expected empty, got %q", in, got)
		}
	}
}

func TestTaskSummaryFromPrompt_RejectsEmptyAndWhitespace(t *testing.T) {
	for _, in := range []string{"", "   ", "\n\n", "\t\t", "✳⚡🎉"} {
		if got := TaskSummaryFromPrompt(in); got != "" {
			t.Errorf("empty-equivalent %q expected empty, got %q", in, got)
		}
	}
}

func TestTaskSummaryFromPrompt_TakesFirstLineOnly(t *testing.T) {
	in := "幫我修 voice_notify\n貼了一大段：\n第三行\n第四行"
	want := "修 voice_notify"
	if got := TaskSummaryFromPrompt(in); got != want {
		t.Errorf("\n got=%q\nwant=%q", got, want)
	}
}

func TestTaskSummaryFromPrompt_RejectsLongPaste(t *testing.T) {
	// First line > 200 runes → assume code paste, drop entirely.
	long := strings.Repeat("阿", 250)
	if got := TaskSummaryFromPrompt(long); got != "" {
		t.Errorf("long paste expected empty, got %q (len=%d)", got, len([]rune(got)))
	}
}

func TestTaskSummaryFromPrompt_CapsAt30Runes(t *testing.T) {
	// 中文 35 字 — should be cut to 30
	long := strings.Repeat("中", 35)
	got := TaskSummaryFromPrompt(long)
	if r := []rune(got); len(r) != 30 {
		t.Errorf("expected 30 runes, got %d (%q)", len(r), got)
	}
}

func TestTaskSummaryFromPrompt_RejectsQuestions(t *testing.T) {
	// Questions are conversation, not task instructions — the stop template
	// "少爺，{summary}的任務完成了" doesn't fit. Drop and let BuildStopMessage
	// fall through to the label template.
	for _, in := range []string{
		"你只移除第一個主詞嗎？還是還沒重新 build",
		"幫我看一下這對不對？",
		"where is the redis client defined?",
		"我要怎麼啟動 hook-dispatcher 比較好？",
	} {
		if got := TaskSummaryFromPrompt(in); got != "" {
			t.Errorf("question %q expected empty, got %q", in, got)
		}
	}
}

func TestTaskSummaryFromPrompt_RewritesMidSentencePronouns(t *testing.T) {
	// Prefix-strip handles leading "我要/我想/...", but mid-sentence "我"
	// (e.g., "看我這邊", "修我寫的 bug") still leaks into the stop template
	// and sounds like the assistant talking about itself. Convert all "我"
	// to "您" so the announcement reads as narration to 少爺.
	cases := []struct {
		name string
		in   string
		want string
	}{
		{"我這邊", "幫我看我這邊的 redis 連線", "看您這邊的 redis 連線"},
		{"我的", "請修我的 commit history", "修您的 commit history"},
		{"中段我", "幫我重啟我寫的 hook handler", "重啟您寫的 hook handler"},
		{"strip 後仍含我", "我要 review 我之前的 PR", "review 您之前的 PR"},
		{"純動詞短語不變", "幫我修 emoji 過濾的 bug", "修 emoji 過濾的 bug"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := TaskSummaryFromPrompt(tc.in)
			if got != tc.want {
				t.Errorf("\n  in=%q\n got=%q\nwant=%q", tc.in, got, tc.want)
			}
		})
	}
}

func TestTaskSummaryFromPrompt_DropsCredentials(t *testing.T) {
	// Sensitive content must NEVER reach TTS — drop entire summary, not redact.
	sensitive := []string{
		"sk-1234567890abcdefghijklmn幫我看",
		"AKIAIOSFODNN7EXAMPLE 幫我設 AWS",
		"ghp_abcdefghijklmnopqrstuvwxyz123456 push 一下",
		"我想 password=Hunter22 改一下",
		"token: abc123xyz 確認看看",
	}
	for _, in := range sensitive {
		if got := TaskSummaryFromPrompt(in); got != "" {
			t.Errorf("sensitive content %q should produce empty, got %q", in, got)
		}
	}
}

// ---------------------------------------------------------------------------
// TaskSummaryFilePath — TMUX_PANE > session_id[:4] > "" priority
// ---------------------------------------------------------------------------

func TestTaskSummaryFilePath_Priority(t *testing.T) {
	t.Setenv("TMUX_PANE", "%3")
	if got := TaskSummaryFilePath("019dfff5abc"); got != "/tmp/claude-task-3.txt" {
		t.Errorf("TMUX_PANE present: got %q", got)
	}
	t.Setenv("TMUX_PANE", "")
	if got := TaskSummaryFilePath("019dfff5abc"); got != "/tmp/claude-task-019d.txt" {
		t.Errorf("session fallback: got %q", got)
	}
	t.Setenv("TMUX_PANE", "")
	if got := TaskSummaryFilePath(""); got != "" {
		t.Errorf("no inputs: should return empty, got %q", got)
	}
	t.Setenv("TMUX_PANE", "")
	if got := TaskSummaryFilePath("abc"); got != "" {
		t.Errorf("session_id < 4 chars: should return empty, got %q", got)
	}
}

// ---------------------------------------------------------------------------
// WriteTaskSummary — dedup + human-summary preservation + atomic write
// ---------------------------------------------------------------------------

func TestWriteTaskSummary_FreshWriteAndDedup(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "task.txt")

	WriteTaskSummary(path, "修 emoji 過濾")
	got, _ := os.ReadFile(path)
	if string(got) != "修 emoji 過濾" {
		t.Fatalf("first write: got %q", got)
	}
	info1, _ := os.Stat(path)

	// Same content → no rewrite (mtime unchanged within filesystem timestamp resolution)
	time.Sleep(20 * time.Millisecond)
	WriteTaskSummary(path, "修 emoji 過濾")
	info2, _ := os.Stat(path)
	if !info1.ModTime().Equal(info2.ModTime()) {
		t.Errorf("dedup failed: mtime changed (%v → %v)", info1.ModTime(), info2.ModTime())
	}

	// Different content within 5min and 6-35 rune old content → preserved (human guard)
	WriteTaskSummary(path, "改 SoundSource bug")
	got, _ = os.ReadFile(path)
	if string(got) != "修 emoji 過濾" {
		t.Errorf("human-guard: expected old preserved, got %q", got)
	}
}

func TestWriteTaskSummary_HumanGuardExpiresAfter5Min(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "task.txt")

	// Plant an "old" summary by writing then back-dating mtime
	WriteTaskSummary(path, "舊 summary")
	old := time.Now().Add(-6 * time.Minute)
	_ = os.Chtimes(path, old, old)

	WriteTaskSummary(path, "新 summary 來覆蓋")
	got, _ := os.ReadFile(path)
	if string(got) != "新 summary 來覆蓋" {
		t.Errorf("expired guard should allow overwrite, got %q", got)
	}
}

func TestWriteTaskSummary_LongOldContentNotProtected(t *testing.T) {
	// Old content > 35 runes → not human-shaped → can be overwritten freely
	dir := t.TempDir()
	path := filepath.Join(dir, "task.txt")
	long := strings.Repeat("舊", 40)
	_ = os.WriteFile(path, []byte(long), 0o644)

	WriteTaskSummary(path, "新")  // < 6 rune fail upstream — but WriteTaskSummary itself accepts any non-empty
	WriteTaskSummary(path, "新 summary OK 覆蓋")
	got, _ := os.ReadFile(path)
	if string(got) != "新 summary OK 覆蓋" {
		t.Errorf("expected overwrite of long old content, got %q", got)
	}
}

func TestWriteTaskSummary_EmptyInputsNoOp(t *testing.T) {
	// path or summary empty → no panic, no write
	WriteTaskSummary("", "abc")
	WriteTaskSummary("/tmp/should-not-exist-claude-test", "")
	if _, err := os.Stat("/tmp/should-not-exist-claude-test"); !os.IsNotExist(err) {
		t.Error("empty summary should not create file")
		os.Remove("/tmp/should-not-exist-claude-test")
	}
}

// ---------------------------------------------------------------------------
// HandleUserPromptSubmit — end-to-end raw JSON → file
// ---------------------------------------------------------------------------

func TestHandleUserPromptSubmit_EndToEnd(t *testing.T) {
	t.Setenv("TMUX_PANE", "%test-end2end")
	path := "/tmp/claude-task-test-end2end.txt"
	defer os.Remove(path)
	os.Remove(path) // clean slate

	HandleUserPromptSubmit(`{"prompt":"幫我修 voice_notify 的 emoji 過濾 bug","session_id":"019dfff5"}`)
	got, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("expected file written: %v", err)
	}
	if string(got) != "修 voice_notify 的 emoji 過濾 bug" {
		t.Errorf("got %q", got)
	}
}

func TestHandleUserPromptSubmit_BadJSONNoPanic(t *testing.T) {
	// Malformed JSON — fail-open, no write, no panic
	HandleUserPromptSubmit(`not json at all`)
	HandleUserPromptSubmit(``)
	HandleUserPromptSubmit(`{}`)
	// success = no panic
}

// ---------------------------------------------------------------------------
// IsSystemPrompt — host-harness template detection (cmux auto-titling, …)
// ---------------------------------------------------------------------------

func TestIsSystemPrompt_MatchesKnownHarnessTemplates(t *testing.T) {
	cases := []string{
		// cmux ≥0.63 workspace auto-titling
		"Generate a session title and pick an icon for the following conversation.",
		"Generate a concise title under 6 words for the chat below.",
		"Generate a brief one-line summary",
		// IDE summarization templates
		"Summarize the following conversation in 2 sentences.",
		"Summarize the above chat",
		// Other auto-naming templates
		"Create a title for this session",
		"Create a name for the workspace",
		"Suggest a title for this conversation",
		// Case-insensitive
		"GENERATE A SESSION TITLE",
		"summarize the conversation",
		// memvault refine / extract / progressive-snapshot pipelines
		// (mcp/memvault/scripts/{extract,extract_progressive}.py spawn
		// `claude -p` with these system-role openings).
		"你是對話記憶提煉專家。分析以下 Claude Code 工作 session transcript",
		"你是記憶品質審查員。以下是從 Claude Code 對話中提煉的記憶 JSON。",
		"你是對話記憶的中途快照員。這是一個進行中的 Claude Code session",
		"你是態度提取專家。從以下記憶 blocks 中提取使用者的偏好",
	}
	for _, in := range cases {
		t.Run(in, func(t *testing.T) {
			if !IsSystemPrompt(in) {
				t.Errorf("expected system-prompt match, got false for %q", in)
			}
		})
	}
}

func TestIsSystemPrompt_RejectsHumanPrompts(t *testing.T) {
	cases := []string{
		"幫我修 voice_notify 的 emoji 過濾 bug",
		"我想加 UserPromptSubmit hook",
		"generate-session.sh 這個檔在哪",
		"Could you generate a test for this?",  // human-phrased, not template
		"請 summarize 這個 PR 給我聽",            // mixed but human
		// "你是 X" prefix but not a system role — must NOT trigger Guard 0.6.
		"你是怎麼處理 cache 的",
		"你是不是該重啟 redis 看看",
		"你是少爺的程式秘書嗎",
		"",
	}
	for _, in := range cases {
		t.Run(in, func(t *testing.T) {
			if IsSystemPrompt(in) {
				t.Errorf("expected NOT system-prompt, got true for %q", in)
			}
		})
	}
}

func TestIsSystemPrompt_TakesFirstLineOnly(t *testing.T) {
	// Multi-line input with template on line 1 → match.
	if !IsSystemPrompt("Generate a session title for the following.\n\n<chat dump>") {
		t.Error("expected match on first line")
	}
	// Template on line 2 → ignore (system prompts always lead with template).
	if IsSystemPrompt("這是我的問題\nGenerate a session title please") {
		t.Error("expected no match when template is not on first line")
	}
}

// ---------------------------------------------------------------------------
// SystemMarkerPath / HandleUserPromptSubmit — marker round-trip
// ---------------------------------------------------------------------------

func TestSystemMarkerPath_Priority(t *testing.T) {
	t.Setenv("TMUX_PANE", "%4")
	if got := SystemMarkerPath("019dfff5abc"); got != "/tmp/claude-system-4.marker" {
		t.Errorf("TMUX_PANE present: got %q", got)
	}
	t.Setenv("TMUX_PANE", "")
	if got := SystemMarkerPath("019dfff5abc"); got != "/tmp/claude-system-019d.marker" {
		t.Errorf("session fallback: got %q", got)
	}
	t.Setenv("TMUX_PANE", "")
	if got := SystemMarkerPath("abc"); got != "" {
		t.Errorf("session_id < 4 chars: should return empty, got %q", got)
	}
}

func TestHandleUserPromptSubmit_SystemPromptDropsMarkerNoTaskFile(t *testing.T) {
	t.Setenv("TMUX_PANE", "%test-cmux")
	taskPath := "/tmp/claude-task-test-cmux.txt"
	markerPath := "/tmp/claude-system-test-cmux.marker"
	defer func() {
		os.Remove(taskPath)
		os.Remove(markerPath)
	}()
	os.Remove(taskPath)
	os.Remove(markerPath)

	HandleUserPromptSubmit(`{"prompt":"Generate a session title and pick an icon for the chat below.","session_id":"019dfff5"}`)

	if _, err := os.Stat(markerPath); err != nil {
		t.Errorf("expected marker file at %s, stat err: %v", markerPath, err)
	}
	if _, err := os.Stat(taskPath); !os.IsNotExist(err) {
		t.Errorf("expected NO task summary file (system prompt should short-circuit), but it exists")
	}
}

func TestHandleUserPromptSubmit_HumanPromptWritesTaskNoMarker(t *testing.T) {
	t.Setenv("TMUX_PANE", "%test-human")
	taskPath := "/tmp/claude-task-test-human.txt"
	markerPath := "/tmp/claude-system-test-human.marker"
	defer func() {
		os.Remove(taskPath)
		os.Remove(markerPath)
	}()
	os.Remove(taskPath)
	os.Remove(markerPath)

	HandleUserPromptSubmit(`{"prompt":"幫我修 cmux 雙播 TTS 的 bug","session_id":"019dfff5"}`)

	if _, err := os.Stat(taskPath); err != nil {
		t.Errorf("expected task file at %s, stat err: %v", taskPath, err)
	}
	if _, err := os.Stat(markerPath); !os.IsNotExist(err) {
		t.Errorf("human prompt should NOT create marker, but it exists")
	}
}
