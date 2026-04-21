package sessionpipeline

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// ---- ShouldSkip / FindTranscript ----------------------------------------

func TestShouldSkipTinyFile(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "tiny.jsonl")
	_ = os.WriteFile(path, []byte("{}\n"), 0o644)
	reason := ShouldSkip(path)
	if !strings.HasPrefix(reason, "trivial: file_size=") || !strings.Contains(reason, "< 3KB") {
		t.Fatalf("expected tiny skip reason, got %q", reason)
	}
}

func TestShouldSkipNoUserMessages(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "no-msgs.jsonl")
	var sb strings.Builder
	line := `{"type":"user","userType":"","message":{"content":"<local-command-stdout>hello</local-command-stdout>"}}`
	for sb.Len() < 5000 {
		sb.WriteString(line)
		sb.WriteByte('\n')
	}
	_ = os.WriteFile(path, []byte(sb.String()), 0o644)
	reason := ShouldSkip(path)
	if !strings.HasPrefix(reason, "trivial: 0 user messages") {
		t.Fatalf("expected 0-user skip reason, got %q", reason)
	}
}

func TestShouldSkipRealUserMessage(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "real.jsonl")
	var sb strings.Builder
	noise := `{"type":"assistant","message":{"content":"ok"}}`
	for sb.Len() < 4000 {
		sb.WriteString(noise)
		sb.WriteByte('\n')
	}
	sb.WriteString(`{"type":"user","userType":"","message":{"content":"please help me"}}`)
	sb.WriteByte('\n')
	_ = os.WriteFile(path, []byte(sb.String()), 0o644)
	if r := ShouldSkip(path); r != "" {
		t.Fatalf("expected no skip, got %q", r)
	}
}

func TestFindTranscript(t *testing.T) {
	dir := t.TempDir()
	proj := filepath.Join(dir, "project-a")
	_ = os.MkdirAll(proj, 0o755)
	session := "abcdef1234567890"
	target := filepath.Join(proj, session+".jsonl")
	_ = os.WriteFile(target, []byte("{}"), 0o644)
	if got := FindTranscript(dir, session); got != target {
		t.Fatalf("find mismatch: got %q want %q", got, target)
	}
}

// ---- Redact --------------------------------------------------------------

func TestRedactLineAPIKeys(t *testing.T) {
	// Each input is chosen so that only the specific pattern fires — the
	// generic_secret catch-all would stomp on values that follow
	// `token:` / `key:` / `password:` prefixes, which is intentional
	// (parity with Python session_redactor).
	cases := map[string]string{
		"curl -H x-ant sk-ant-abcdefghijklmnopqrstuvwxyz1234": "[REDACTED:anthropic_key]",
		"opening sk-0123456789abcdefghij0123456789abcd for":   "[REDACTED:openai_key]",
		"commit with ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 rights": "[REDACTED:github_token]",
		"call with Bearer AbcDefGhiJklMnoPqrStuVwxYz12345":    "Bearer [REDACTED:token]",
	}
	for input, want := range cases {
		got, cats := redactLine(input)
		if !strings.Contains(got, want) {
			t.Errorf("redactLine(%q) missing %q; got %q", input, want, got)
		}
		if len(cats) == 0 {
			t.Errorf("redactLine(%q) expected categories, got none", input)
		}
	}
}

func TestRedactLinePasswordVariants(t *testing.T) {
	line := `password: secret12345`
	got, cats := redactLine(line)
	if !strings.Contains(got, "[REDACTED]") {
		t.Fatalf("missing redaction: %s", got)
	}
	if cats["password"] == 0 && cats["generic_secret"] == 0 {
		t.Fatalf("expected password/generic_secret category; got %v", cats)
	}
}

func TestRedactJSONLLineStringLeaf(t *testing.T) {
	line := `{"role":"user","message":"hey password=hunter2abcdef"}` + "\n"
	cats := map[string]int{}
	out, n := redactJSONLLine(line, cats)
	if n == 0 {
		t.Fatalf("expected at least one redaction")
	}
	if !strings.Contains(out, "[REDACTED]") {
		t.Fatalf("output should mention redaction: %s", out)
	}
	// Make sure it still parses back
	var obj map[string]any
	if err := json.Unmarshal([]byte(strings.TrimRight(out, "\n")), &obj); err != nil {
		t.Fatalf("output is not valid JSON: %v\n%s", err, out)
	}
}

func TestStageRedactWritesBack(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "sample.jsonl")
	body := `{"type":"user","message":{"content":"curl -H \"Authorization: Bearer abcdefghijklmnopqrstuvwxyz1234567890\" https://api"}}` + "\n"
	body += `{"type":"assistant","message":{"content":"OK"}}` + "\n"
	_ = os.WriteFile(path, []byte(body), 0o644)

	r := StageRedact("sess-test", path)
	if !r.Success {
		t.Fatalf("stage failed: %s", r.Error)
	}
	data, _ := os.ReadFile(path)
	if !strings.Contains(string(data), "[REDACTED:token]") {
		t.Fatalf("file not redacted:\n%s", data)
	}
}

// ---- Reflect -------------------------------------------------------------

func TestCalculateQualityScoreSuccess(t *testing.T) {
	s := transcriptStats{
		TurnCount:           5,
		UserMessageCount:    3,
		ToolCallCount:       10,
		ToolSuccessCount:    9,
		ToolErrorCount:      1,
		AssistantTextTokens: 50,
		TotalTokens:         100,
		CompletionSignal:    0.8,
	}
	outcome, score := calculateQualityScore(s)
	if outcome != "success" {
		t.Errorf("expected success, got %s", outcome)
	}
	if score < 0.5 || score > 1.0 {
		t.Errorf("score out of expected range: %v", score)
	}
}

func TestCalculateQualityScoreFailure(t *testing.T) {
	s := transcriptStats{
		TurnCount:        0, // zero turns → failure
		UserMessageCount: 0,
	}
	outcome, _ := calculateQualityScore(s)
	if outcome != "failure" {
		t.Errorf("expected failure outcome, got %s", outcome)
	}
}

func TestExtractFailurePatterns(t *testing.T) {
	s := transcriptStats{
		ErrorMessages: []string{
			"HTTP 429 rate limit exceeded",
			"Permission denied on /tmp/x",
			"No such file: /etc/passwd",
		},
	}
	got := extractFailurePatterns(s)
	wantAny := map[string]bool{"rate_limit": true, "permission_denied": true, "file_not_found": true}
	for _, g := range got {
		if wantAny[g] {
			wantAny[g] = false
		}
	}
	missing := []string{}
	for k, still := range wantAny {
		if still {
			missing = append(missing, k)
		}
	}
	if len(missing) > 0 {
		t.Fatalf("missing patterns: %v — got %v", missing, got)
	}
}

func TestAnalyzeTranscriptSmoke(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "t.jsonl")
	body := ""
	// 3 user messages + 3 assistant with tool_use (calls) and one tool_error
	body += `{"type":"user","message":{"role":"user","content":"do it"},"timestamp":1000}` + "\n"
	body += `{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Sure"},{"type":"tool_use","name":"Read"}]},"timestamp":1001}` + "\n"
	body += `{"type":"user","message":{"role":"user","content":[{"type":"tool_result","content":"ok result"}]},"timestamp":1002}` + "\n"
	body += `{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Done and finished."}]},"timestamp":1003}` + "\n"
	_ = os.WriteFile(path, []byte(body), 0o644)

	m := AnalyzeTranscript(path, "smoke")
	if m.SessionID != "smoke" {
		t.Fatalf("session_id not preserved")
	}
	if m.TurnCount != 2 {
		t.Errorf("expected 2 turns, got %d", m.TurnCount)
	}
	if m.ToolCallCount == 0 {
		t.Errorf("expected tool calls to be counted")
	}
	if m.ToolSuccessCount == 0 {
		t.Errorf("expected tool successes to be counted")
	}
	if m.DurationSecs != 3 {
		t.Errorf("expected duration=3s got %d", m.DurationSecs)
	}
}

// ---- Runner sanity -------------------------------------------------------

func TestRunPipelineTrivialSkip(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "tiny.jsonl")
	_ = os.WriteFile(path, []byte("{}"), 0o644)
	r := RunPipeline("trivial-sess", path)
	if len(r.Stages) == 0 {
		t.Fatal("expected at least one stage entry")
	}
	if r.Stages[0].Name != "pre-filter" {
		t.Errorf("expected pre-filter first, got %s", r.Stages[0].Name)
	}
	skipped, _ := r.Stages[0].Details["skipped"].(bool)
	if !skipped {
		t.Error("pre-filter must mark skipped for trivial file")
	}
}
