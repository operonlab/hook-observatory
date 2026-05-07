package voicenotify

import (
	"encoding/json"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

// fillerPrefixes are conversational filler phrases the user habitually opens
// with. Listed longest-first so that "你能不能幫我" wins over "幫我" when both
// would match. The list is hand-curated from observed dialogue; keep it in
// sync with feedback_user_speech_patterns.md.
var fillerPrefixes = []string{
	"你能不能幫我", "可不可以幫我",
	"能不能幫我", "你可以幫我",
	"麻煩你幫我", "我想請你",
	"我接下來",
	"你幫我", "請幫我", "麻煩你", "煩請你",
	"我想要", "我希望", "我發現",
	"我必須", "我打算", "我準備",
	"能不能", "可不可以",
	"幫一下", "幫忙", "我想",
	"我要", "我來", "我得", "我先", "我該", "我去",
	"幫我", "麻煩", "煩請",
	"勞煩", "順便", "請",
}

// sensitiveRegexes detect content that must never reach TTS playback.
// Matches → entire summary is dropped (not redacted) so the audio stays silent
// rather than reading partial credentials aloud.
var sensitiveRegexes = []*regexp.Regexp{
	regexp.MustCompile(`sk-[A-Za-z0-9_-]{20,}`),                            // OpenAI / Anthropic style
	regexp.MustCompile(`AKIA[0-9A-Z]{16}`),                                 // AWS access key
	regexp.MustCompile(`ghp_[A-Za-z0-9]{20,}`),                             // GitHub personal token
	regexp.MustCompile(`xox[baprs]-[A-Za-z0-9-]{10,}`),                     // Slack token
	regexp.MustCompile(`(?i)(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*\S+`),
}

// systemPromptRegexes match prompts emitted by host harnesses (cmux, IDE
// integrations, automation pipelines) rather than by 少爺. cmux ≥0.63 spawns a
// background Claude session per workspace to auto-name the tab, sending
// templates like "Generate a session title and ..." — its Stop event would
// otherwise trigger a duplicate "任務完成了" announcement on top of the human
// session's own Stop.
//
// Match → suppress the summary AND drop a marker file so the Stop handler can
// skip TTS for that session entirely (see SystemMarkerPath / Guard 0.6).
var systemPromptRegexes = []*regexp.Regexp{
	regexp.MustCompile(`(?i)^generate (?:a |an |the )?(?:session |conversation |chat |workspace )?title`),
	regexp.MustCompile(`(?i)^generate (?:a |an )?(?:concise|short|brief|one[- ]?line)`),
	regexp.MustCompile(`(?i)^summari[sz]e (?:the )?(?:following|conversation|above|chat|session)`),
	regexp.MustCompile(`(?i)^create (?:a |an )?(?:title|summary|name|label) for`),
	regexp.MustCompile(`(?i)^suggest (?:a |an )?(?:title|name|label)`),
}

// IsSystemPrompt returns true when prompt looks like a host-harness template
// (cmux auto-titling, IDE summarization, etc.) that should never produce a
// 少爺-facing TTS announcement.
func IsSystemPrompt(prompt string) bool {
	first := strings.TrimSpace(prompt)
	if first == "" {
		return false
	}
	if idx := strings.IndexByte(first, '\n'); idx >= 0 {
		first = strings.TrimSpace(first[:idx])
	}
	for _, re := range systemPromptRegexes {
		if re.MatchString(first) {
			return true
		}
	}
	return false
}

// SystemMarkerPath resolves the per-session marker file used to flag a Stop
// event as belonging to a host-harness background session. Path layout mirrors
// TaskSummaryFilePath so reader (Guard 0.6) and writer (HandleUserPromptSubmit)
// always agree.
func SystemMarkerPath(sessionID string) string {
	if pane := os.Getenv("TMUX_PANE"); pane != "" {
		return "/tmp/claude-system-" + strings.ReplaceAll(pane, "%", "") + ".marker"
	}
	if len(sessionID) >= 4 {
		return "/tmp/claude-system-" + sessionID[:4] + ".marker"
	}
	return ""
}

const (
	taskSummaryMaxRunes         = 30
	taskSummaryMinRunes         = 6
	taskSummaryFirstLineMaxRune = 200
	taskSummaryHumanGuardMin    = 6
	taskSummaryHumanGuardMax    = 35
	taskSummaryHumanGuardWindow = 5 * time.Minute
)

// runeLen counts Unicode code points in s.
func runeLen(s string) int {
	n := 0
	for range s {
		n++
	}
	return n
}

// TaskSummaryFromPrompt runs the summary pipeline.
// Returns "" when the prompt should not produce a summary (short reply, long
// paste, sensitive content, emoji-only, …). The caller MUST treat "" as
// "skip write" — never persist an empty summary.
func TaskSummaryFromPrompt(prompt string) string {
	if prompt == "" {
		return ""
	}
	first := prompt
	if idx := strings.IndexByte(first, '\n'); idx >= 0 {
		first = first[:idx]
	}
	first = strings.TrimSpace(first)
	if first == "" {
		return ""
	}
	if runeLen(first) > taskSummaryFirstLineMaxRune {
		return ""
	}
	first = stripEmoji(first)
	if first == "" {
		return ""
	}
	for _, prefix := range fillerPrefixes {
		if strings.HasPrefix(first, prefix) {
			first = strings.TrimSpace(first[len(prefix):])
			break
		}
	}
	if first == "" {
		return ""
	}
	for _, re := range sensitiveRegexes {
		if re.MatchString(first) {
			return ""
		}
	}
	// Question/conversation rejection: the stop template
	// "少爺，{summary}的任務完成了" only fits action phrases. A prompt with
	// "?" or "？" is the user asking Claude something, not a task to read
	// back on completion — drop it so BuildStopMessage falls through to the
	// label template ("少爺，{label}任務完成了").
	if strings.ContainsAny(first, "?？") {
		return ""
	}
	// First-person → second-person rewrite: prefix-strip already removes
	// leading "我要 / 我想 / ...", but mid-sentence pronouns ("看我這邊",
	// "修我寫的 bug") still leak through. Convert all remaining "我" to "您"
	// so the result reads as third-party narration to 少爺.
	first = strings.ReplaceAll(first, "我", "您")
	if runeLen(first) < taskSummaryMinRunes {
		return ""
	}
	if r := []rune(first); len(r) > taskSummaryMaxRunes {
		first = string(r[:taskSummaryMaxRunes])
	}
	return first
}

// TaskSummaryFilePath resolves where to read/write the summary file.
// Priority: TMUX_PANE > sessionID first 4 chars > "" (caller skips).
// Empty TMUX_PANE in non-tmux contexts is intentionally allowed to fall back
// onto session_id so headless runs (cron, fleet) still get per-session
// isolation. Aligns with statusline.sh:97 (SID="${SESSION_ID:0:4}").
func TaskSummaryFilePath(sessionID string) string {
	if pane := os.Getenv("TMUX_PANE"); pane != "" {
		return "/tmp/claude-task-" + strings.ReplaceAll(pane, "%", "") + ".txt"
	}
	if len(sessionID) >= 4 {
		return "/tmp/claude-task-" + sessionID[:4] + ".txt"
	}
	return ""
}

// WriteTaskSummary writes summary to path with three guards:
//   - dedup: skip if existing content already matches
//   - human-summary preservation: if existing file is recent (< 5min) and its
//     length sits in the human-curated range (6-35 runes), keep it. This
//     gives Claude / the user a window to overwrite with a precise summary
//     that auto-extraction shouldn't immediately stomp on.
//   - atomic write: tmp file + rename so a torn write never leaves partial
//     data for getTaskSummary() to read.
//
// Fail-open: any IO error returns silently — TTS must never block hooks.
func WriteTaskSummary(path, summary string) {
	if path == "" || summary == "" {
		return
	}
	if existing, err := os.ReadFile(path); err == nil {
		old := strings.TrimSpace(string(existing))
		if old == summary {
			return
		}
		if info, statErr := os.Stat(path); statErr == nil {
			oldRunes := runeLen(old)
			if oldRunes >= taskSummaryHumanGuardMin && oldRunes <= taskSummaryHumanGuardMax &&
				time.Since(info.ModTime()) < taskSummaryHumanGuardWindow {
				return
			}
		}
	}
	dir := filepath.Dir(path)
	tmp, err := os.CreateTemp(dir, ".claude-task-*.tmp")
	if err != nil {
		return
	}
	tmpName := tmp.Name()
	if _, err := tmp.WriteString(summary); err != nil {
		tmp.Close()
		os.Remove(tmpName)
		return
	}
	if err := tmp.Close(); err != nil {
		os.Remove(tmpName)
		return
	}
	_ = os.Rename(tmpName, path)
}

// HandleUserPromptSubmit is the package entrypoint called by the
// handlers-package thin wrapper. Parses the raw JSON, runs the pipeline,
// writes the summary file. Fail-open on every error.
//
// System-prompt short-circuit: if the prompt matches a host-harness template
// (cmux auto-titling, etc.), drop a marker file and stop. The marker is
// consumed once by Guard 0.6 in the Stop handler so the background session's
// Stop event is silently dropped instead of producing a duplicate TTS.
func HandleUserPromptSubmit(rawJSON string) {
	var data struct {
		Prompt    string `json:"prompt"`
		SessionID string `json:"session_id"`
	}
	if err := json.Unmarshal([]byte(rawJSON), &data); err != nil {
		return
	}
	if IsSystemPrompt(data.Prompt) {
		if mp := SystemMarkerPath(data.SessionID); mp != "" {
			_ = os.WriteFile(mp, []byte{}, 0o644)
		}
		return
	}
	summary := TaskSummaryFromPrompt(data.Prompt)
	if summary == "" {
		return
	}
	path := TaskSummaryFilePath(data.SessionID)
	if path == "" {
		return
	}
	WriteTaskSummary(path, summary)
}
