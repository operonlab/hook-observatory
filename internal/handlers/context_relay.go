package handlers

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"github.com/joneshong/hook-observatory/internal/core"
)

func init() {
	entry := core.Entry{
		Handler:    contextRelayHandle,
		ModuleName: "context_relay",
	}
	core.Register("SessionStart", entry)
	core.Register("PreCompact", entry)
}

const (
	crHandoffTTL = 300 // 5 minutes
	crHandoffDir = "/tmp/handoff"
)

var crPaneRe = regexp.MustCompile(`^pane-\d+$`)

func crBaseURL() string {
	return core.Cfg().GetService("session_channel_url")
}

func crLocalKey() string {
	if k := os.Getenv("SESSION_CHANNEL_KEY"); k != "" {
		return k
	}
	return "change-me-in-production"
}

func crPaneID() string {
	pane := os.Getenv("TMUX_PANE")
	if pane == "" {
		return ""
	}
	pid := strings.ReplaceAll(pane, "%", "pane-")
	if crPaneRe.MatchString(pid) {
		return pid
	}
	return ""
}

func crPaneNum() string {
	pane := os.Getenv("TMUX_PANE")
	if pane == "" {
		return ""
	}
	num := strings.ReplaceAll(pane, "%", "")
	for _, c := range num {
		if c < '0' || c > '9' {
			return ""
		}
	}
	return num
}

// ---------------------------------------------------------------------------
// Main handler
// ---------------------------------------------------------------------------

func contextRelayHandle(eventType, _ string, _ map[string]any, _ string) core.HookResult {
	switch eventType {
	case "SessionStart":
		return crSessionStart()
	case "PreCompact":
		return core.Message("💡 Context 即將壓縮。如需完整交棒到新 session，可執行 `handoff spawn`")
	}
	return core.Allow()
}

func crSessionStart() core.HookResult {
	pane := crPaneID()
	paneNum := crPaneNum()
	if pane == "" || paneNum == "" {
		return core.Allow()
	}

	// Priority 1: Redis via session-channel
	redisMsg := crReadFromRedis(pane)
	if redisMsg != nil {
		text, _ := redisMsg["text"].(string)
		tag, _ := redisMsg["tag"].(string)
		if text != "" && tag != "consumed" && text != "__consumed__" {
			crCleanupHandoff(pane, paneNum)
			return core.Message(text)
		}
	}

	// Priority 2: file fallback
	fileData := crReadFromFile(paneNum)
	if fileData != nil {
		handoffMD, _ := fileData["handoff_md"].(string)
		sourcePane, _ := fileData["source_pane"].(string)
		if sourcePane == "" {
			sourcePane = "?"
		}
		ts := fmt.Sprintf("%v", fileData["timestamp"])
		role, _ := fileData["role"].(string)
		if handoffMD != "" {
			crCleanupHandoff(pane, paneNum)
			return core.Message(crFormatHandoff(handoffMD, sourcePane, ts, role))
		}
	}

	return core.Allow()
}

// ---------------------------------------------------------------------------
// Redis via HTTP
// ---------------------------------------------------------------------------

func crReadFromRedis(pane string) map[string]any {
	base := crBaseURL()
	if base == "" {
		return nil
	}
	topic := "handoff:" + pane
	url := fmt.Sprintf("%s/api/messages/%s?count=50", base, topic)
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return nil
	}
	req.Header.Set("x-local-key", crLocalKey())
	client := &http.Client{Timeout: 5 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return nil
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil
	}
	var data map[string]any
	if err := json.Unmarshal(body, &data); err != nil {
		return nil
	}
	msgs, _ := data["messages"].([]any)
	if len(msgs) == 0 {
		return nil
	}
	// xrange oldest-first → take last
	last, ok := msgs[len(msgs)-1].(map[string]any)
	if !ok {
		return nil
	}
	return last
}

func crConsumeRedis(pane string) {
	base := crBaseURL()
	if base == "" {
		return
	}
	topic := "handoff:" + pane
	payload := map[string]any{
		"topic":  topic,
		"text":   "__consumed__",
		"sender": pane,
		"tag":    "consumed",
	}
	b, err := json.Marshal(payload)
	if err != nil {
		return
	}
	req, err := http.NewRequest("POST", base+"/api/messages", strings.NewReader(string(b)))
	if err != nil {
		return
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("x-local-key", crLocalKey())
	client := &http.Client{Timeout: 3 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return
	}
	defer resp.Body.Close()
	io.Copy(io.Discard, resp.Body)
}

// ---------------------------------------------------------------------------
// File fallback
// ---------------------------------------------------------------------------

func crReadFromFile(paneNum string) map[string]any {
	if paneNum == "" {
		return nil
	}
	for _, c := range paneNum {
		if c < '0' || c > '9' {
			return nil
		}
	}
	path := filepath.Join(crHandoffDir, paneNum+".json")
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var out map[string]any
	if err := json.Unmarshal(data, &out); err != nil {
		return nil
	}
	// TTL check
	if ts, ok := out["timestamp"].(float64); ok && ts > 0 {
		if time.Since(time.Unix(int64(ts), 0)) > crHandoffTTL*time.Second {
			_ = os.Remove(path)
			return nil
		}
	}
	return out
}

func crCleanupHandoff(pane, paneNum string) {
	// File cleanup
	if paneNum != "" {
		_ = os.Remove(filepath.Join(crHandoffDir, paneNum+".json"))
	}
	// Redis cleanup
	crConsumeRedis(pane)
}

// ---------------------------------------------------------------------------
// Format
// ---------------------------------------------------------------------------

func crFormatHandoff(handoffMD, source, tsStr string, role string) string {
	age := ""
	if ts, err := parseFloat(tsStr); err == nil && ts > 0 {
		delta := int(time.Since(time.Unix(int64(ts), 0)).Seconds())
		switch {
		case delta < 60:
			age = fmt.Sprintf("%d 秒前", delta)
		case delta < 3600:
			age = fmt.Sprintf("%d 分鐘前", delta/60)
		default:
			age = fmt.Sprintf("%d 小時前", delta/3600)
		}
	}
	header := fmt.Sprintf("[Context Relay] 接續自 %s 的工作", source)
	if age != "" {
		header += fmt.Sprintf("(%s)", age)
	}
	if role != "" {
		header += fmt.Sprintf("\n**角色**: %s", role)
	}
	return fmt.Sprintf("%s\n\n%s", header, handoffMD)
}

func parseFloat(s string) (float64, error) {
	var f float64
	_, err := fmt.Sscanf(s, "%f", &f)
	return f, err
}
