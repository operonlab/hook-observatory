package handlers

// attitude_signal.go — Go port of handlers/attitude_signal.py
//
// Collects implicit attitude signals from hook events:
//   - Notification (tool_denied)  → autonomy_level correction
//   - SessionEnd                  → session statistics from spool
//
// Output: ~/Claude/memvault/corrections/auto/{YYYY-MM}/{YYYY-MM-DD}.jsonl

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/joneshong/hook-dispatcher/internal/core"
)

func init() {
	entry := core.Entry{
		Matcher:    "",
		Handler:    attitudeSignalHandle,
		Critical:   false,
		ModuleName: "attitude_signal",
	}
	core.Register("Notification", entry)
	core.Register("SessionEnd", entry)
}

func attitudeSignalHandle(eventType, toolName string, _ map[string]any, rawInput string) core.HookResult {
	switch eventType {
	case "Notification":
		return asHandleNotification(toolName, rawInput)
	case "SessionEnd":
		return asHandleSessionEnd(rawInput)
	default:
		return core.Allow()
	}
}

// ---------------------------------------------------------------------------
// Notification: detect tool denials
// ---------------------------------------------------------------------------

func asHandleNotification(toolName, rawInput string) core.HookResult {
	var data map[string]any
	if rawInput != "" {
		if err := json.Unmarshal([]byte(rawInput), &data); err != nil {
			return core.Allow()
		}
	}

	message, _ := data["message"].(string)
	notifData, _ := data["data"].(map[string]any)
	if notifData == nil {
		notifData = data
	}

	deniedTool := ""
	if strings.Contains(strings.ToLower(message), "denied") {
		if v, _ := notifData["tool_name"].(string); v != "" {
			deniedTool = v
		} else {
			deniedTool = toolName
		}
	} else if t, _ := notifData["type"].(string); t == "tool_denied" {
		deniedTool, _ = notifData["tool_name"].(string)
	}

	if deniedTool != "" {
		sessionID, _ := notifData["session_id"].(string)
		asWriteCorrection(
			"autonomy_level",
			"使用者 deny "+deniedTool+", 偏好更多確認再執行",
			sessionID,
		)
	}

	return core.Allow()
}

// ---------------------------------------------------------------------------
// SessionEnd: analyze spool statistics for the session
// ---------------------------------------------------------------------------

func asHandleSessionEnd(rawInput string) core.HookResult {
	var data map[string]any
	if rawInput != "" {
		if err := json.Unmarshal([]byte(rawInput), &data); err != nil {
			return core.Allow()
		}
	}

	sessionID := ""
	if inner, ok := data["data"].(map[string]any); ok {
		sessionID, _ = inner["session_id"].(string)
	}
	if sessionID == "" {
		sessionID, _ = data["session_id"].(string)
	}
	if sessionID == "" {
		return core.Allow()
	}

	spoolFile := filepath.Join(core.Cfg().GetSpoolDir(), "events.jsonl")
	raw, err := os.ReadFile(spoolFile)
	if err != nil {
		return core.Allow()
	}

	var sessionEvents []map[string]any
	for _, line := range strings.Split(string(raw), "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		var evt map[string]any
		if err := json.Unmarshal([]byte(line), &evt); err != nil {
			continue
		}
		evtData, _ := evt["data"].(map[string]any)
		evtSID, _ := evtData["session_id"].(string)
		if evtSID == sessionID {
			sessionEvents = append(sessionEvents, evt)
		}
	}

	if len(sessionEvents) == 0 {
		return core.Allow()
	}

	denyCount := 0
	messageCount := 0
	toolCount := 0

	for _, evt := range sessionEvents {
		evtType, _ := evt["event_type"].(string)
		evtData, _ := evt["data"].(map[string]any)

		switch evtType {
		case "Notification":
			msg, _ := evtData["message"].(string)
			tp, _ := evtData["type"].(string)
			if strings.Contains(strings.ToLower(msg), "denied") || tp == "tool_denied" {
				denyCount++
			}
		case "UserPromptSubmit":
			messageCount++
		case "PreToolUse", "PostToolUse":
			toolCount++
		}
	}

	if denyCount >= 3 {
		asWriteCorrection(
			"autonomy_level",
			"本 session deny "+itoa(denyCount)+" 次, 使用者偏好更多確認",
			sessionID,
		)
	}

	if messageCount > 0 && float64(toolCount)/float64(messageCount) > 15.0 {
		asWriteCorrection(
			"verbosity",
			"高工具密度 ("+itoa(toolCount)+"/"+itoa(messageCount)+"), 使用者可能偏好精簡對話",
			sessionID,
		)
	}

	return core.Allow()
}

// ---------------------------------------------------------------------------
// Helper: append a correction record
// ---------------------------------------------------------------------------

func asWriteCorrection(category, fact, sessionID string) {
	home, _ := os.UserHomeDir()
	correctionsDir := filepath.Join(home, "Claude", "memvault", "corrections", "auto")

	now := time.Now()
	monthDir := filepath.Join(correctionsDir, now.Format("2006-01"))
	if err := os.MkdirAll(monthDir, 0o755); err != nil {
		return
	}

	outFile := filepath.Join(monthDir, now.Format("2006-01-02")+".jsonl")
	record := map[string]any{
		"fact":       fact,
		"category":   category,
		"session_id": sessionID,
		"timestamp":  now.Format("2006-01-02T15:04:05"),
		"source":     "attitude_signal",
	}
	line, err := json.Marshal(record)
	if err != nil {
		return
	}

	f, err := os.OpenFile(outFile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	defer f.Close()
	f.Write(line)
	f.Write([]byte("\n"))
}
