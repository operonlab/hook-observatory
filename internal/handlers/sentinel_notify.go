package handlers

// sentinel_notify.go — Go port of handlers/sentinel_notify.py
//
// PreToolUse+Bash → POST /notify (service entering maintenance)
// PostToolUse+Bash → POST /resolve (command completed)

import (
	"encoding/json"
	"os"
	"regexp"

	"github.com/joneshong/hook-dispatcher/internal/core"
)

func init() {
	for _, ev := range []string{"PreToolUse", "PostToolUse"} {
		core.Register(ev, core.Entry{
			Matcher:    "Bash",
			Handler:    sentinelNotifyHandle,
			Critical:   false,
			ModuleName: "sentinel_notify",
		})
	}
}

var sentinelPatterns = []struct {
	re      *regexp.Regexp
	service string
}{
	{regexp.MustCompile(`workshop-services\.sh\s+(restart|stop|start)`), "workshop-services"},
	{regexp.MustCompile(`docker\s+(restart|stop|start)\s+ws-infra`), "docker-infra"},
	{regexp.MustCompile(`uvicorn.*--port\s+(880[0-9]|10[0-3]\d{2})`), "core"},
	{regexp.MustCompile(`kill\s.*880[1-9]|kill\s.*10[0-3]\d{2}`), "kill-service"},
	{regexp.MustCompile(`nginx\s+-s\s+(reload|stop|quit)`), "nginx"},
	{regexp.MustCompile(`pnpm\s+run\s+build`), "frontend-build"},
	{regexp.MustCompile(`docker\s+restart\s+ws-infra-postgres`), "postgres"},
	{regexp.MustCompile(`docker\s+restart\s+ws-infra-redis`), "redis"},
}

func sentinelNotifyHandle(eventType, toolName string, toolInput map[string]any, _ string) core.HookResult {
	if toolName != "Bash" {
		return core.Allow()
	}
	command, _ := toolInput["command"].(string)
	if command == "" {
		return core.Allow()
	}

	service := sentinelDetectService(command)
	if service == "" {
		return core.Allow()
	}

	sentinelBase := core.Cfg().GetService("sentinel_url")
	if sentinelBase == "" {
		return core.Allow()
	}

	agentID := os.Getenv("CLAUDE_SESSION_ID")
	if agentID == "" {
		agentID = "unknown-agent"
	}

	var endpoint string
	var payload map[string]any

	switch eventType {
	case "PreToolUse":
		endpoint = "notify"
		payload = map[string]any{
			"service":            service,
			"action":             truncate(command, 100),
			"agent_id":           agentID,
			"estimated_duration": 300,
		}
	case "PostToolUse":
		endpoint = "resolve"
		payload = map[string]any{
			"service":  service,
			"agent_id": agentID,
			"result":   "completed",
		}
	default:
		return core.Allow()
	}

	sentinelFire(sentinelBase, endpoint, payload)
	return core.Allow()
}

func sentinelDetectService(command string) string {
	for _, p := range sentinelPatterns {
		if p.re.MatchString(command) {
			return p.service
		}
	}
	return ""
}

func sentinelFire(base, endpoint string, payload map[string]any) {
	data, err := json.Marshal(payload)
	if err != nil {
		return
	}
	_ = core.RunBackground([]string{
		"curl", "-s", "-X", "POST",
		base + "/" + endpoint,
		"-H", "Content-Type: application/json",
		"-d", string(data),
		"--connect-timeout", "2",
		"--max-time", "5",
	}, "")
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}
