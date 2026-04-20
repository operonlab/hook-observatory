// Package handlers — session_channel.go
// SessionStart + Stop handler — auto-announce to session-channel station.
// Fire-and-forget HTTP POST via curl subprocess.
// Fails silently if station is not running.
package handlers

import (
	"encoding/json"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/joneshong/hook-dispatcher/internal/core"
)

const (
	sessionChannelLocalKey        = "change-me-in-production"
	sessionChannelDebounceSeconds = 60
)

func init() {
	for _, ev := range []string{"SessionStart", "Stop"} {
		core.Register(ev, core.Entry{
			Matcher:    "",
			Handler:    sessionChannelHandle,
			Critical:   false,
			ModuleName: "session_channel",
		})
	}
}

func sessionChannelHandle(eventType, _ string, _ map[string]any, rawInput string) core.HookResult {
	switch eventType {
	case "SessionStart":
		return sessionChannelHandleStart(rawInput)
	case "Stop":
		return sessionChannelHandleStop(rawInput)
	}
	return core.Allow()
}

func sessionChannelHandleStart(rawInput string) core.HookResult {
	cwd := ""
	if strings.TrimSpace(rawInput) != "" {
		var parsed map[string]any
		if err := json.Unmarshal([]byte(rawInput), &parsed); err == nil {
			if toolInput, ok := parsed["tool_input"].(map[string]any); ok {
				cwd, _ = toolInput["cwd"].(string)
			}
		}
	}

	home, _ := os.UserHomeDir()
	shortCwd := "?"
	if cwd != "" {
		shortCwd = strings.Replace(cwd, home, "~", 1)
	}

	sessionChannelSendAsync("sessions", fmt.Sprintf("joined — %s", shortCwd), "normal", "start")
	return core.Allow()
}

func sessionChannelHandleStop(_ string) core.HookResult {
	if sessionChannelIsDebounced() {
		return core.Allow()
	}

	task := sessionChannelReadTaskState()
	if task == "" {
		return core.Allow()
	}

	pane := os.Getenv("TMUX_PANE")
	relayMeta := ""
	if pane != "" {
		paneSafe := strings.ReplaceAll(pane, "%", "")
		if _, err := os.Stat(fmt.Sprintf("/tmp/relay-pending-%s.channel", paneSafe)); err == nil {
			relayMeta = fmt.Sprintf(" [relay:%%%s]", paneSafe)
		}
	}

	sessionChannelSendAsync("sessions", fmt.Sprintf("done: %s%s", task, relayMeta), "normal", "stop")
	return core.Allow()
}

func sessionChannelPaneID() string {
	pane := os.Getenv("TMUX_PANE")
	if pane == "" {
		return fmt.Sprintf("pid-%d", os.Getpid())
	}
	return strings.ReplaceAll(pane, "%", "pane-")
}

func sessionChannelSendAsync(topic, text, priority, tag string) {
	baseURL := core.Cfg().GetService("session_channel_url")
	if baseURL == "" {
		baseURL = "http://127.0.0.1:10101"
	}

	body := map[string]any{
		"topic":    topic,
		"text":     text,
		"sender":   sessionChannelPaneID(),
		"priority": priority,
	}
	if tag != "" {
		body["tag"] = tag
	}

	bodyJSON, err := json.Marshal(body)
	if err != nil {
		return
	}

	// Use curl for fire-and-forget, matching Python's run_background(cmd) pattern
	url := baseURL + "/api/messages"
	_ = core.RunBackground([]string{
		"curl", "-s", "-o", "/dev/null", "-m", "2",
		"-X", "POST", url,
		"-H", "Content-Type: application/json",
		"-H", fmt.Sprintf("x-local-key: %s", sessionChannelLocalKey),
		"-d", string(bodyJSON),
	}, "")
}

func sessionChannelReadTaskState() string {
	pane := os.Getenv("TMUX_PANE")
	if pane == "" {
		return ""
	}
	stateFile := fmt.Sprintf("/tmp/claude-task-%s.txt", strings.ReplaceAll(pane, "%", ""))
	data, err := os.ReadFile(stateFile)
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(data))
}

func sessionChannelIsDebounced() bool {
	paneID := sessionChannelPaneID()
	debounceFile := fmt.Sprintf("/tmp/session-channel-stop-debounce-%s.ts", paneID)
	now := float64(time.Now().Unix())

	data, err := os.ReadFile(debounceFile)
	if err == nil {
		ts, err := strconv.ParseFloat(strings.TrimSpace(string(data)), 64)
		if err == nil && now-ts < float64(sessionChannelDebounceSeconds) {
			return true
		}
	}

	_ = os.WriteFile(debounceFile, []byte(fmt.Sprintf("%.6f", now)), 0o644)
	return false
}
