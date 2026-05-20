// Package handlers — session_channel.go
// SessionStart / PreToolUse / UserPromptSubmit / Stop / SessionEnd handler —
// auto-announce to session-channel for cross-agent statline + inbox push.
// Fire-and-forget HTTP POST via curl subprocess.
// Fails silently if station is not running.
package handlers

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/joneshong/hook-dispatcher/internal/core"
	portregistry "github.com/joneshong/hook-dispatcher/internal/portregistry"
)

const (
	sessionChannelLocalKey        = "change-me-in-production"
	sessionChannelDebounceSeconds = 60
	sessionChannelHeartbeatSecs   = 30
	sessionChannelCtxFreshSecs    = 30
	sessionChannelInboxFetchSecs  = 2
	sessionChannelInboxMaxItems   = 6
)

// sessionChannelBaseURL returns the configured session-channel URL, or the
// port-registry default (session-channel = 10101). Centralising the lookup
// keeps the two call sites (inbox poll + async send) in lock-step.
func sessionChannelBaseURL() string {
	if v := core.Cfg().GetService("session_channel_url"); v != "" {
		return v
	}
	return portregistry.URL("session-channel", "", 10101)
}

// Topics polled on UserPromptSubmit. Order = display order in injected text.
// Both `broadcast` (singular, dashboard footer default) and `broadcasts`
// (plural, /channel send recommended form) are accepted to be forgiving.
var sessionChannelInboxTopics = []string{"broadcasts", "broadcast", "handoffs", "tasks"}

func init() {
	for _, ev := range []string{"SessionStart", "PreToolUse", "Stop", "SessionEnd", "UserPromptSubmit"} {
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
	case "UserPromptSubmit":
		return sessionChannelHandleUserPromptSubmit(rawInput)
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
	// Always publish the tool event (one per actual tool call) so the dashboard
	// can show "what is this pane doing right now?". The heartbeat snapshot
	// below is throttled because it carries ctx%/branch/task — those change
	// slowly; tool-call observability needs per-call granularity.
	sessionChannelPublishTool(rawInput)

	if sessionChannelHeartbeatThrottled() {
		return core.Allow()
	}
	sessionChannelPublishSnapshot("heartbeat", rawInput)
	return core.Allow()
}

// sessionChannelPublishTool — emit a `tool` tag to the agents topic so
// observers see "pane %5 just ran Read ~/path/foo". Idempotent on rawInput:
// silently no-ops if tool_name cannot be parsed.
func sessionChannelPublishTool(rawInput string) {
	var p map[string]any
	if err := json.Unmarshal([]byte(rawInput), &p); err != nil {
		return
	}
	toolName, _ := p["tool_name"].(string)
	if toolName == "" {
		return
	}

	preview := sessionChannelToolPreview(toolName, p["tool_input"])

	meta := sessionChannelCollectMeta(rawInput)
	meta["tool_name"] = toolName
	if preview != "" {
		meta["tool_args_preview"] = preview
	}

	text := toolName
	if preview != "" {
		text = toolName + " " + preview
	}
	if len(text) > 80 {
		text = text[:77] + "..."
	}

	sessionChannelSendAsync("agents", text, "normal", "tool", meta)
}

// sessionChannelToolPreview builds a short human-readable summary of a tool
// invocation. Each tool gets a hand-picked field that is most descriptive.
// Returns empty string if no useful preview can be extracted.
func sessionChannelToolPreview(toolName string, toolInput any) string {
	inp, ok := toolInput.(map[string]any)
	if !ok {
		return ""
	}
	pick := func(key string, maxLen int) string {
		s, _ := inp[key].(string)
		s = strings.TrimSpace(s)
		if s == "" {
			return ""
		}
		s = strings.ReplaceAll(s, "\n", " ")
		if maxLen > 0 && len(s) > maxLen {
			s = s[:maxLen-1] + "…"
		}
		return s
	}
	shortPath := func(s string) string {
		if home, _ := os.UserHomeDir(); home != "" && strings.HasPrefix(s, home) {
			s = "~" + s[len(home):]
		}
		if len(s) > 48 {
			s = "…" + s[len(s)-47:]
		}
		return s
	}
	switch toolName {
	case "Read", "Write", "Edit", "NotebookEdit":
		if p := pick("file_path", 0); p != "" {
			return shortPath(p)
		}
	case "Bash":
		return pick("command", 50)
	case "Grep":
		return pick("pattern", 50)
	case "Glob":
		return pick("pattern", 50)
	case "WebFetch", "WebSearch":
		if u := pick("url", 50); u != "" {
			return u
		}
		return pick("query", 50)
	case "Task", "Agent":
		return pick("description", 50)
	case "Skill":
		return pick("skill", 50)
	}
	return ""
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

// ── UserPromptSubmit inbox push ────────────────────────────────────────────
//
// Fetch unread messages on watched topics, filter (drop self-sent; for
// `tasks` only keep ones targeted at this pane or untargeted), advance the
// per-pane cursor, and inject a compact summary into the prompt context.
// Fail-open on any error — the user's prompt always goes through.

func sessionChannelHandleUserPromptSubmit(_ string) core.HookResult {
	cursor := sessionChannelLoadCursor()
	mySender := sessionChannelPaneID()
	myPane := os.Getenv("TMUX_PANE")

	type inboxItem struct {
		topic, sender, text, tag, timeAgo string
	}
	var items []inboxItem

	baseURL := sessionChannelBaseURL()
	client := &http.Client{Timeout: time.Duration(sessionChannelInboxFetchSecs) * time.Second}

	for _, topic := range sessionChannelInboxTopics {
		since := cursor[topic]
		if since == "" {
			// First time: anchor at "now - 1h" so we don't flood with stale messages.
			anchorMs := time.Now().Add(-1 * time.Hour).UnixMilli()
			since = fmt.Sprintf("%d-0", anchorMs)
		}
		msgs, lastID := sessionChannelFetchSince(client, baseURL, topic, since)
		if lastID != "" {
			cursor[topic] = lastID
		}
		for _, m := range msgs {
			sender, _ := m["sender"].(string)
			if sender == mySender {
				continue // skip self-sent
			}
			tag, _ := m["tag"].(string)
			text, _ := m["text"].(string)
			meta, _ := m["_meta"].(map[string]any)

			// tasks + handoffs topics: respect target_pane (skip if explicitly
			// addressed to a different pane).
			if topic == "tasks" || topic == "handoffs" {
				if target, ok := meta["target_pane"].(string); ok && target != "" {
					if target != myPane && target != mySender {
						continue
					}
				}
			}

			displayText := sessionChannelTrunc(text, 120)
			if topic == "handoffs" {
				if path, ok := meta["handoff_path"].(string); ok && path != "" {
					displayText = fmt.Sprintf("%s → READ %s", displayText, path)
				}
			}

			items = append(items, inboxItem{
				topic:   topic,
				sender:  sender,
				text:    displayText,
				tag:     tag,
				timeAgo: sessionChannelMsgAgeStr(m),
			})
			if len(items) >= sessionChannelInboxMaxItems {
				break
			}
		}
		if len(items) >= sessionChannelInboxMaxItems {
			break
		}
	}

	// Persist cursor even when no new items (keeps anchor advancing).
	sessionChannelSaveCursor(cursor)

	if len(items) == 0 {
		return core.Allow()
	}

	var b strings.Builder
	b.WriteString(fmt.Sprintf("📬 session-channel inbox (%d unread):\n", len(items)))
	for _, it := range items {
		tagPart := ""
		if it.tag != "" {
			tagPart = " #" + it.tag
		}
		b.WriteString(fmt.Sprintf("  [%s]%s %s: %s · %s\n",
			it.topic, tagPart, it.sender, it.text, it.timeAgo))
	}
	b.WriteString("(use /channel read <topic> for full thread)")
	return core.TextResult(b.String())
}

func sessionChannelFetchSince(client *http.Client, baseURL, topic, since string) ([]map[string]any, string) {
	url := fmt.Sprintf("%s/api/messages/%s?since=%s&count=20",
		baseURL, topic, since)
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return nil, ""
	}
	req.Header.Set("X-Local-Key", sessionChannelLocalKey)
	resp, err := client.Do(req)
	if err != nil {
		return nil, ""
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		_, _ = io.Copy(io.Discard, resp.Body)
		return nil, ""
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, ""
	}
	var d struct {
		Messages []map[string]any `json:"messages"`
	}
	if err := json.Unmarshal(body, &d); err != nil {
		return nil, ""
	}
	if len(d.Messages) == 0 {
		return nil, ""
	}
	// xrange returns the `since` ID inclusive — drop the head if it matches.
	out := d.Messages
	if id, _ := out[0]["id"].(string); id == since && len(out) > 1 {
		out = out[1:]
	} else if id == since {
		return nil, since
	}
	lastID, _ := out[len(out)-1]["id"].(string)
	return out, lastID
}

func sessionChannelMsgAgeStr(m map[string]any) string {
	id, _ := m["id"].(string)
	tsPart := strings.SplitN(id, "-", 2)[0]
	tsMs, err := strconv.ParseInt(tsPart, 10, 64)
	if err != nil {
		return "?"
	}
	age := time.Since(time.UnixMilli(tsMs))
	if age < time.Minute {
		return fmt.Sprintf("%ds ago", int(age.Seconds()))
	}
	if age < time.Hour {
		return fmt.Sprintf("%dm ago", int(age.Minutes()))
	}
	return fmt.Sprintf("%dh ago", int(age.Hours()))
}

func sessionChannelTrunc(s string, n int) string {
	s = strings.TrimSpace(strings.ReplaceAll(s, "\n", " "))
	if len(s) <= n {
		return s
	}
	return s[:n] + "…"
}

func sessionChannelCursorPath() string {
	pane := os.Getenv("TMUX_PANE")
	paneSafe := strings.ReplaceAll(pane, "%", "")
	if paneSafe == "" {
		paneSafe = strconv.Itoa(os.Getpid())
	}
	return fmt.Sprintf("/tmp/channel-cursor-%s.json", paneSafe)
}

func sessionChannelLoadCursor() map[string]string {
	out := map[string]string{}
	data, err := os.ReadFile(sessionChannelCursorPath())
	if err != nil {
		return out
	}
	_ = json.Unmarshal(data, &out)
	return out
}

func sessionChannelSaveCursor(c map[string]string) {
	data, err := json.Marshal(c)
	if err != nil {
		return
	}
	_ = os.WriteFile(sessionChannelCursorPath(), data, 0o644)
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
	baseURL := sessionChannelBaseURL()

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
