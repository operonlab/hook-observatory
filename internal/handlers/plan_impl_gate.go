package handlers

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/joneshong/hook-observatory/internal/core"
)

func init() {
	core.Register("PostToolUse", core.Entry{
		Matcher:    "",
		Handler:    planImplGatePostToolUse,
		Critical:   false,
		ModuleName: "plan_impl_gate",
	})
	core.Register("UserPromptSubmit", core.Entry{
		Matcher:    "",
		Handler:    planImplGateUserPrompt,
		Critical:   false,
		ModuleName: "plan_impl_gate",
	})
}

const (
	pigMarkerPrefix = ".plan-approved-"
	pigMarkerTTL    = time.Hour
)

// pigMarkerDir returns the directory where plan-approved markers are stored.
func pigMarkerDir() string {
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".hook-observatory", "markers")
}

// pigMarkerPath returns the full path to the session's plan-approved marker.
func pigMarkerPath() string {
	sid := os.Getenv("CLAUDE_SESSION_ID")
	if sid == "" {
		sid = "unknown"
	}
	return filepath.Join(pigMarkerDir(), pigMarkerPrefix+sid)
}

// planImplGatePostToolUse handles the PostToolUse+ExitPlanMode event.
// Writes a marker file with timestamp and plan_path.
func planImplGatePostToolUse(eventType, toolName string, toolInput map[string]any, _ string) core.HookResult {
	if eventType != "PostToolUse" || toolName != "ExitPlanMode" {
		return core.Allow()
	}
	return pigOnExitPlanMode(toolInput)
}

// planImplGateUserPrompt handles the UserPromptSubmit event.
// If a plan-approved marker exists and is fresh, injects a reminder.
func planImplGateUserPrompt(eventType, _ string, _ map[string]any, _ string) core.HookResult {
	if eventType != "UserPromptSubmit" {
		return core.Allow()
	}
	return pigOnUserPrompt()
}

// ---------------------------------------------------------------------------
// Internal logic
// ---------------------------------------------------------------------------

type pigMarkerData struct {
	Timestamp float64 `json:"timestamp"`
	PlanPath  string  `json:"plan_path"`
}

func pigOnExitPlanMode(toolInput map[string]any) core.HookResult {
	marker := pigMarkerPath()
	if err := os.MkdirAll(filepath.Dir(marker), 0o755); err != nil {
		return core.Allow() // fail-open
	}

	planPath, _ := toolInput["plan_path"].(string)
	data := pigMarkerData{
		Timestamp: float64(time.Now().UnixNano()) / 1e9,
		PlanPath:  planPath,
	}

	raw, err := json.Marshal(data)
	if err != nil {
		return core.Allow()
	}
	_ = os.WriteFile(marker, raw, 0o644) // fail-open
	return core.Allow()
}

func pigOnUserPrompt() core.HookResult {
	marker := pigMarkerPath()

	raw, err := os.ReadFile(marker)
	if err != nil {
		return core.Allow() // marker doesn't exist
	}

	var data pigMarkerData
	if err := json.Unmarshal(raw, &data); err != nil {
		return core.Allow()
	}

	// Check TTL
	age := time.Since(time.Unix(int64(data.Timestamp), int64((data.Timestamp-float64(int64(data.Timestamp)))*1e9)))
	if age > pigMarkerTTL {
		_ = os.Remove(marker)
		return core.Allow()
	}

	// One-shot: delete marker before injecting reminder
	_ = os.Remove(marker)

	var pathHint string
	if data.PlanPath != "" {
		pathHint = "\n- Plan file: `" + data.PlanPath + "`"
	}

	return core.TextResult(
		"## Plan-to-Impl Gate\n" +
			"剛完成計畫階段 (plan mode 消耗了大量 context)。建議:\n" +
			"1. 將計畫中的關鍵決策存到 memory (避免 compact 後遺失)\n" +
			"2. 考慮開新 session 以乾淨 context 開始實作" + pathHint,
	)
}

// ---------------------------------------------------------------------------
// Ensure strings import is used (pigMarkerPrefix uses it indirectly — guard)
// ---------------------------------------------------------------------------

var _ = strings.TrimSpace // keep import live if refactored
