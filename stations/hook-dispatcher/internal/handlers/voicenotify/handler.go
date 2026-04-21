package voicenotify

import (
	"encoding/json"
	"math/rand"
	"os"
	"os/exec"
	"syscall"
)

// Handle is the Go port of voice_notify.py:handle. Returns true if the caller
// should treat the event as "handled" (the core dispatcher ignores return
// and always returns Allow — this is kept for future use / tests).
func Handle(eventType, toolName string, rawInput string) {
	if os.Getenv("CLAUDE_VOICE") == "0" {
		return
	}

	switch eventType {
	case "PreToolUse":
		if toolName == "AskUserQuestion" {
			ident := GetIdent("")
			CancelPendingTTS(ident)
			if DebounceOK("ask", "") {
				EnqueueTTS(AskPhrases[rand.Intn(len(AskPhrases))])
			}
		}

	case "SubagentStart":
		data := parseEventData(rawInput)
		ident := GetIdent(stringField(data, "session_id"))
		TrackSubagentStart(ident)

	case "SubagentStop":
		data := parseEventData(rawInput)
		sessionID := stringField(data, "session_id")
		ident := GetIdent(sessionID)
		TrackSubagentStop(ident)
		if DebounceOK("subagent_stop", sessionID) {
			playSoundEffect()
		}

	case "Stop":
		data := parseEventData(rawInput)
		sessionID := stringField(data, "session_id")
		ident := GetIdent(sessionID)

		// Guard 0: skip non-Claude Stop events.
		hookName := stringField(data, "hook_event_name")
		if hookName != "" && hookName != "Stop" {
			return
		}
		// Guard 0.5: skip teammate/sub-agent Stops.
		agentType := stringField(data, "agent_type")
		if agentType == "" {
			agentType = stringField(data, "subagent_type")
		}
		if agentType != "" && TeammateTypes[agentType] {
			return
		}
		// Guard 1: skip re-entrant stop hook.
		if boolField(data, "stop_hook_active") {
			return
		}
		// Guard 2: skip intermediate-state messages.
		if IsIntermediate(stringField(data, "last_assistant_message")) {
			return
		}
		// Guards 1.5 + 1.7 inside handleStopWithTracking.
		if DebounceOK("stop", sessionID) {
			handleStopWithTracking(ident)
		}
	}
}

func handleStopWithTracking(ident string) {
	msg := BuildStopMessage()
	if GetRedis() == nil {
		EnqueueTTS(msg)
		return
	}

	active := ActiveSubagents(ident)
	lastAct := LastActivityTs(ident)
	now := nowSeconds()

	// Guard 1.5: sub-agents still running → defer.
	// Guard 1.7: recent sub-agent activity within settle window → defer.
	if active > 0 || (lastAct > 0 && (now-lastAct) < float64(SettleWindow)) {
		deferAnnouncement(ident, msg)
		return
	}
	EnqueueTTS(msg)
}

func deferAnnouncement(ident, msg string) {
	payload, err := json.Marshal(map[string]any{"msg": msg, "queued_at": nowSeconds()})
	if err != nil {
		EnqueueTTS(msg)
		return
	}
	if err := SetPending(ident, string(payload)); err != nil {
		EnqueueTTS(msg)
		return
	}
	SpawnChecker(ident)
}

func playSoundEffect() {
	if !SubagentSoundEnabled() {
		return
	}
	if _, err := os.Stat(SubagentSoundPath); err != nil {
		return
	}
	cmd := exec.Command("afplay", "-v", SubagentVolume(), SubagentSoundPath)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	cmd.Stdout = nil
	cmd.Stderr = nil
	if err := cmd.Start(); err != nil {
		return
	}
	_ = cmd.Process.Release()
}

func parseEventData(raw string) map[string]any {
	if raw == "" {
		return nil
	}
	var m map[string]any
	if err := json.Unmarshal([]byte(raw), &m); err != nil {
		return nil
	}
	return m
}

func stringField(m map[string]any, key string) string {
	if m == nil {
		return ""
	}
	if v, ok := m[key].(string); ok {
		return v
	}
	return ""
}

func boolField(m map[string]any, key string) bool {
	if m == nil {
		return false
	}
	if v, ok := m[key].(bool); ok {
		return v
	}
	return false
}
