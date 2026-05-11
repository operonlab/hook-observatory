// Package handlers — session_channel.go
// SessionStart / PreToolUse / Stop / SessionEnd handler — auto-announce to
// session-channel station for cross-agent statline and pane discovery.
// Fire-and-forget HTTP POST via curl subprocess.
// Fails silently if station is not running.
package handlers

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/joneshong/hook-dispatcher/internal/core"
)

const (
	sessionChannelLocalKey        = "change-me-in-production"
	sessionChannelDebounceSeconds = 60
	sessionChannelHeartbeatSecs   = 30
	sessionChannelCtxFreshSecs    = 30
)

func init() {
	for _, ev := range []string{"SessionStart", "PreToolUse", "Stop", "SessionEnd"} {
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
	case "PreToolUse":
		return sessionChannelHandlePreTool(rawInput)
	case "Stop":
		return sessionChannelHandleStop(rawInput)
	case "SessionEnd":
		return sessionChannelHandleSessionEnd(rawInput)
	}
	return core.Allow()
}

// ── Event handlers ─────────────────────────────────────────────────────────

func sessionChannelHandleStart(rawInput string) core.HookResult {
	cwd := sessionChannelExtractCwd(rawInput)
	home, _ := os.UserHomeDir()
	shortCwd := "?"
	if cwd != "" {
		shortCwd = strings.Replace(cwd, home, "~", 1)
	}
	sessionChannelSendAsync("sessions", fmt.Sprintf("joined — %s", shortCwd), "normal", "start", nil)
	sessionChannelPublishSnapshot("announce", rawInput)
	return core.Allow()
}

func sessionChannelHandlePreTool(rawInput string) core.HookResult {
	if sessionChannelHeartbeatThrottled() {
		return core.Allow()
	}
	sessionChannelPublishSnapshot("heartbeat", rawInput)
	return core.Allow()
}

func sessionChannelHandleStop(rawInput string) core.HookResult {
	if sessionChannelIsDebounced() {
		return core.Allow()
	}

	task := sessionChannelReadTaskState()
	if task != "" {
		pane := os.Getenv("TMUX_PANE")
		relayMeta := ""
		if pane != "" {
			paneSafe := strings.ReplaceAll(pane, "%", "")
			if _, err := os.Stat(fmt.Sprintf("/tmp/relay-pending-%s.channel", paneSafe)); err == nil {
				relayMeta = fmt.Sprintf(" [relay:%%%s]", paneSafe)
			}
		}
		sessionChannelSendAsync("sessions", fmt.Sprintf("done: %s%s", task, relayMeta), "normal", "stop", nil)
	}
	sessionChannelPublishSnapshot("heartbeat", rawInput)
	return core.Allow()
}

func sessionChannelHandleSessionEnd(rawInput string) core.HookResult {
	sessionChannelPublishSnapshot("leave", rawInput)
	return core.Allow()
}

// ── Metadata collection ────────────────────────────────────────────────────

func sessionChannelExtractCwd(rawInput string) string {
	if strings.TrimSpace(rawInput) == "" {
		cwd, _ := os.Getwd()
		return cwd
	}
	var parsed map[string]any
	if err := json.Unmarshal([]byte(rawInput), &parsed); err != nil {
		cwd, _ := os.Getwd()
		return cwd
	}
	if v, ok := parsed["cwd"].(string); ok && v != "" {
		return v
	}
	if ws, ok := parsed["workspace"].(map[string]any); ok {
		if v, ok := ws["current_dir"].(string); ok && v != "" {
			return v
		}
	}
	if ti, ok := parsed["tool_input"].(map[string]any); ok {
		if v, ok := ti["cwd"].(string); ok && v != "" {
			return v
		}
	}
	cwd, _ := os.Getwd()
	return cwd
}

func sessionChannelExtractSID(rawInput string) string {
	if strings.TrimSpace(rawInput) == "" {
		return ""
	}
	var parsed map[string]any
	if err := json.Unmarshal([]byte(rawInput), &parsed); err != nil {
		return ""
	}
	if v, ok := parsed["session_id"].(string); ok {
		if len(v) > 8 {
			return v[:8]
		}
		return v
	}
	return ""
}

func sessionChannelDetectRole() string {
	pane := os.Getenv("TMUX_PANE")
	if pane != "" {
		paneSafe := strings.ReplaceAll(pane, "%", "")
		if _, err := os.Stat(fmt.Sprintf("/tmp/relay-pending-%s.channel", paneSafe)); err == nil {
			return "worker"
		}
	}
	if r := os.Getenv("CC_PANE_ROLE"); r != "" {
		return r
	}
	return "main"
}

func sessionChannelHostname() string {
	host, err := os.Hostname()
	if err != nil {
		return "?"
	}
	return strings.SplitN(host, ".", 2)[0]
}

// readCtxBridge returns the latest statusline-written ctx snapshot if fresh.
// Format: {"pct":<f>,"thr":<n>,"win":<n>,"ts":<unix>,"model":"<id>","sid":"<8>"}
func sessionChannelReadCtxBridge() map[string]any {
	pane := os.Getenv("TMUX_PANE")
	paneSafe := strings.ReplaceAll(pane, "%", "")
	if paneSafe == "" {
		paneSafe = strconv.Itoa(os.Getpid())
	}
	path := filepath.Join("/tmp/.claude-statusline", "ctx-"+paneSafe+".json")
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var out map[string]any
	if err := json.Unmarshal(data, &out); err != nil {
		return nil
	}
	if ts, ok := out["ts"].(float64); ok {
		if time.Now().Unix()-int64(ts) > sessionChannelCtxFreshSecs {
			return nil
		}
	}
	return out
}

func sessionChannelGitBranch(cwd string) string {
	if cwd == "" {
		return ""
	}
	// Resolve git path explicitly — hook env's PATH may be sparse.
	gitPath, err := exec.LookPath("git")
	if err != nil {
		// Common macOS / Linux locations.
		for _, p := range []string{"/usr/bin/git", "/usr/local/bin/git", "/opt/homebrew/bin/git"} {
			if _, statErr := os.Stat(p); statErr == nil {
				gitPath = p
				break
			}
		}
		if gitPath == "" {
			return ""
		}
	}
	// Let git walk upward to find .git — handles monorepo subdirs.
	cmd := exec.Command(gitPath, "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD")
	cmd.Env = append(os.Environ(), "GIT_OPTIONAL_LOCKS=0")
	done := make(chan struct{})
	var out []byte
	var runErr error
	go func() {
		out, runErr = cmd.Output()
		close(done)
	}()
	select {
	case <-done:
		if runErr != nil {
			// non-git directory or detached HEAD
			return ""
		}
		branch := strings.TrimSpace(string(out))
		if branch == "HEAD" {
			return "detached"
		}
		return branch
	case <-time.After(1500 * time.Millisecond):
		_ = cmd.Process.Kill()
		return ""
	}
}

func sessionChannelCollectMeta(rawInput string) map[string]any {
	cwd := sessionChannelExtractCwd(rawInput)
	ctx := sessionChannelReadCtxBridge()
	pane := os.Getenv("TMUX_PANE")
	if pane == "" {
		pane = fmt.Sprintf("pid-%d", os.Getpid())
	}
	home, _ := os.UserHomeDir()
	displayCwd := cwd
	if home != "" && strings.HasPrefix(cwd, home) {
		displayCwd = "~" + strings.TrimPrefix(cwd, home)
	}

	model := ""
	var ctxPct any
	if ctx != nil {
		if v, ok := ctx["model"].(string); ok {
			model = v
		}
		if v, ok := ctx["pct"]; ok {
			ctxPct = v
		}
	}

	meta := map[string]any{
		"v":       1,
		"host":    sessionChannelHostname(),
		"pane":    pane,
		"sid":     sessionChannelExtractSID(rawInput),
		"cli":     "claude",
		"model":   model,
		"role":    sessionChannelDetectRole(),
		"branch":  sessionChannelGitBranch(cwd),
		"cwd":     displayCwd,
		"ctx_pct": ctxPct,
		"task":    sessionChannelReadTaskState(),
		"ts":      time.Now().Unix(),
	}
	return meta
}

func sessionChannelPublishSnapshot(tag, rawInput string) {
	meta := sessionChannelCollectMeta(rawInput)
	bits := []string{}
	cli, _ := meta["cli"].(string)
	role, _ := meta["role"].(string)
	if cli != "" || role != "" {
		bits = append(bits, fmt.Sprintf("%s/%s", strDefault(cli, "?"), strDefault(role, "?")))
	}
	if br, ok := meta["branch"].(string); ok && br != "" {
		bits = append(bits, "on "+br)
	}
	if pct, ok := meta["ctx_pct"].(float64); ok {
		bits = append(bits, fmt.Sprintf("ctx %.0f%%", pct))
	}
	if t, ok := meta["task"].(string); ok && t != "" {
		if len(t) > 48 {
			t = t[:48]
		}
		bits = append(bits, t)
	}
	text := strings.Join(bits, " · ")
	if text == "" {
		text = fmt.Sprintf("%s %s", cli, tag)
	}
	sessionChannelSendAsync("agents", text, "normal", tag, meta)
}

func strDefault(s, fallback string) string {
	if s == "" {
		return fallback
	}
	return s
}

// ── Throttle / debounce helpers ───────────────────────────────────────────

func sessionChannelHeartbeatThrottled() bool {
	paneID := sessionChannelPaneID()
	path := fmt.Sprintf("/tmp/agent-hb-%s.ts", paneID)
	now := float64(time.Now().Unix())
	if data, err := os.ReadFile(path); err == nil {
		if ts, perr := strconv.ParseFloat(strings.TrimSpace(string(data)), 64); perr == nil {
			if now-ts < float64(sessionChannelHeartbeatSecs) {
				return true
			}
		}
	}
	_ = os.WriteFile(path, []byte(fmt.Sprintf("%.6f", now)), 0o644)
	return false
}

// ── Send + small utilities ─────────────────────────────────────────────────

func sessionChannelPaneID() string {
	pane := os.Getenv("TMUX_PANE")
	if pane == "" {
		return fmt.Sprintf("pid-%d", os.Getpid())
	}
	return strings.ReplaceAll(pane, "%", "pane-")
}

func sessionChannelSendAsync(topic, text, priority, tag string, meta map[string]any) {
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
	if meta != nil {
		body["_meta"] = meta
	}

	bodyJSON, err := json.Marshal(body)
	if err != nil {
		return
	}

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

	if data, err := os.ReadFile(debounceFile); err == nil {
		if ts, perr := strconv.ParseFloat(strings.TrimSpace(string(data)), 64); perr == nil {
			if now-ts < float64(sessionChannelDebounceSeconds) {
				return true
			}
		}
	}
	_ = os.WriteFile(debounceFile, []byte(fmt.Sprintf("%.6f", now)), 0o644)
	return false
}
