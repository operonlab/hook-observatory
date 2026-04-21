package voicenotify

import (
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// intermediateRE matches tail patterns in the assistant's last message that
// signal work-in-progress rather than completion.  Direct port of the Python
// _INTERMEDIATE_PATTERNS list (order and case-insensitivity preserved).
var intermediateRE = regexp.MustCompile(`(?i)` + strings.Join([]string{
	// Chinese patterns
	`接下來`,
	`下一步`,
	`繼續\s*(處理|執行|進行)`,
	`我(會|將|來|先)`,
	`(那麼|好的|首先|然後)，?\s*(我|讓)`,
	`先(處理|檢查|看看|確認|完成)`,
	`(開始|著手)(處理|進行|執行)`,
	`讓我(再|繼續|先|來)`,
	// English patterns
	`let me continue`,
	`I'll now\b`,
	`I will now\b`,
	`next,?\s*I`,
	`moving on to`,
	`let me (?:check|read|look|fix|update|run|create|implement|start|explore|analyze)`,
	`now (?:let me|I'll|I will)`,
	`(?:first|then),?\s*(?:let me|I'll|I need to)`,
	`starting (?:with|by|to)`,
	`I need to (?:first|also|still)`,
	// Question patterns
	`\?\s*$`,
	`您(覺得|認為|希望|想要|選擇|確認)`,
	`請(選擇|確認|決定|告訴我)`,
}, "|"))

// IsIntermediate returns true if the tail of msg matches any in-progress pattern.
func IsIntermediate(msg string) bool {
	if msg == "" {
		return false
	}
	tail := msg
	if len(tail) > 300 {
		tail = tail[len(tail)-300:]
	}
	return intermediateRE.MatchString(tail)
}

// BuildStopMessage assembles the "少爺，…任務完成了" announcement.
func BuildStopMessage() string {
	if summary := getTaskSummary(); summary != "" {
		return "少爺，" + summary + "的任務完成了"
	}
	if label := getLabel(); label != "" {
		return "少爺，" + label + "任務完成了"
	}
	return "少爺，任務完成了"
}

// getTaskSummary reads (and unlinks) the one-shot task state file written by
// Claude per rules/voice-state.md.
func getTaskSummary() string {
	pane := os.Getenv("TMUX_PANE")
	if pane == "" {
		return ""
	}
	paneSafe := strings.ReplaceAll(pane, "%", "")
	path := "/tmp/claude-task-" + paneSafe + ".txt"
	data, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	_ = os.Remove(path) // one-shot cleanup
	summary := strings.TrimSpace(string(data))
	if summary == "" {
		return ""
	}
	// 50-char cap matches Python behaviour.
	if r := []rune(summary); len(r) > 50 {
		return string(r[:50])
	}
	return summary
}

// getLabel resolves a display label from CLAUDE_LABEL env → tmux pane/window →
// cwd basename fallback.
func getLabel() string {
	if v := os.Getenv("CLAUDE_LABEL"); v != "" {
		return v
	}
	if pane := os.Getenv("TMUX_PANE"); pane != "" {
		if lbl := tmuxLabel(pane); lbl != "" {
			return lbl
		}
	}
	cwd, err := os.Getwd()
	if err != nil {
		return ""
	}
	return filepath.Base(cwd)
}

// tmuxLabel mirrors voice_notify._tmux_label. Tries #W, then pane title,
// falling back to 視窗X面板Y using Chinese numerals.
func tmuxLabel(pane string) string {
	shellDefaults := map[string]bool{
		"zsh": true, "bash": true, "fish": true, "sh": true,
		"python": true, "python3": true, "node": true, "": true,
	}

	winName := tmuxDisplay(pane, "#W")
	if winName != "" && !shellDefaults[winName] {
		return winName
	}

	title := tmuxDisplay(pane, "#{pane_title}")
	title = strings.TrimLeftFunc(title, func(r rune) bool {
		return !(isWordChar(r))
	})
	skip := map[string]bool{
		"": true, "-zsh": true, "-bash": true,
		"Claude Code": true, "Gemini CLI": true, "Codex CLI": true,
	}
	if title != "" && !skip[title] && !strings.Contains(title, "@") {
		return title
	}

	winIdx := tmuxDisplay(pane, "#I")
	if winIdx == "" {
		return ""
	}
	paneIdx := tmuxDisplay(pane, "#P")
	w := cnNumeral(winIdx)
	p := cnNumeral(paneIdx)
	return "視窗" + w + "面板" + p
}

func tmuxDisplay(pane, fmt string) string {
	cmd := exec.Command("tmux", "display-message", "-t", pane, "-p", fmt)
	cmd.Stderr = nil
	done := make(chan struct{})
	var out []byte
	var err error
	go func() {
		out, err = cmd.Output()
		close(done)
	}()
	select {
	case <-time.After(2 * time.Second):
		if cmd.Process != nil {
			_ = cmd.Process.Kill()
		}
		<-done
		return ""
	case <-done:
	}
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}

func cnNumeral(s string) string {
	if n, err := strconv.Atoi(s); err == nil && n >= 0 && n <= 9 {
		return NumCN[n]
	}
	return s
}

func isWordChar(r rune) bool {
	if r == '_' {
		return true
	}
	if r >= '0' && r <= '9' {
		return true
	}
	if r >= 'a' && r <= 'z' {
		return true
	}
	if r >= 'A' && r <= 'Z' {
		return true
	}
	// Treat CJK as word characters so Chinese titles pass through.
	if r > 0x7F {
		return true
	}
	return false
}
