package handlers

import (
	"github.com/joneshong/hook-observatory/internal/core"
	"github.com/joneshong/hook-observatory/internal/handlers/voicenotify"
)

// task_summary handler — auto-extracts a 30-rune task summary from each user
// prompt and writes it to the same file getTaskSummary() in voicenotify/detect.go
// reads on Stop. Replaces the old voice-state.md self-discipline rule, which
// in practice was never followed and left TTS announcing the first prompt of
// every session forever.
//
// Pipeline lives in voicenotify/task_summary.go (TaskSummaryFromPrompt +
// TaskSummaryFilePath + WriteTaskSummary). This file is just the dispatcher
// registration glue.
func init() {
	// Critical: true — task_summary writing is < 1ms (file IO only) and must
	// run before Stop reads the file. As deferrable it was being budget-skipped
	// behind slow external (memvault HTTP) handlers that consumed the 5s
	// shared deferrable budget.
	core.Register("UserPromptSubmit", core.Entry{
		Matcher:    "",
		Handler:    taskSummaryUserPrompt,
		Critical:   true,
		ModuleName: "task_summary",
	})
}

func taskSummaryUserPrompt(eventType, _ string, _ map[string]any, raw string) core.HookResult {
	if eventType != "UserPromptSubmit" {
		return core.Allow()
	}
	voicenotify.HandleUserPromptSubmit(raw)
	return core.Allow()
}
