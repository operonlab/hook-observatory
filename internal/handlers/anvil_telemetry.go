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
		Handler:    anvilTelemetryHandle,
		ModuleName: "anvil_telemetry",
	}
	core.Register("UserPromptSubmit", entry)
	core.Register("PostToolUse", entry)
	core.Register("SessionStart", entry)
}

// ---------------------------------------------------------------------------
// Constants & registry
// ---------------------------------------------------------------------------

var (
	anvilAliasMap = map[string]string{
		"r": "prompt-router",
	}
	anvilTestPrefixes = []string{"_", "test-"}
	anvilTestExact    = map[string]bool{
		"test-skill": true, "test-verify": true,
		"general-purpose": true, "commit": true,
	}
	anvilTestDigitsRe  = regexp.MustCompile(`^skill-\d+$`)
	anvilCommandNameRe = regexp.MustCompile(`<command-name>/([^<]+)</command-name>`)
	anvilMCPProxyTools = map[string]bool{
		"mcp__mcpproxy__call_tool_read":        true,
		"mcp__mcpproxy__call_tool_write":       true,
		"mcp__mcpproxy__call_tool_destructive": true,
	}
	anvilCLIBuiltins = map[string]bool{
		"clear": true, "exit": true, "context": true, "mcp": true,
		"login": true, "model": true, "config": true, "help": true,
		"compact": true, "fast": true, "cost": true, "memory": true,
		"permissions": true, "agents": true, "skills": true,
		"terminal-setup": true, "vim": true, "bug": true, "doctor": true,
		"release-notes": true, "init": true, "review": true,
		"allowed-tools": true, "listen": true, "status-bar": true,
		"add-dir": true, "loop": true,
	}

	anvilMCPRegistry map[string]string
	anvilCLIRegistry map[string]string
)

func init() {
	// Load tool_registry.json from the hook-observatory assets dir.
	// HOOK_OBSERVATORY_ROOT (preferred) / HOOK_DISPATCHER_ROOT (backward-compat) override default.
	root := os.Getenv("HOOK_OBSERVATORY_ROOT")
	if root == "" {
		root = os.Getenv("HOOK_DISPATCHER_ROOT")
	}
	if root == "" {
		home, _ := os.UserHomeDir()
		root = filepath.Join(home, "workshop", "stations", "hook-observatory")
	}
	regPath := filepath.Join(root, "assets", "tool_registry.json")
	if data, err := os.ReadFile(regPath); err == nil {
		var reg struct {
			MCPServers  map[string]string `json:"mcp_servers"`
			CLICommands map[string]string `json:"cli_commands"`
		}
		if json.Unmarshal(data, &reg) == nil {
			anvilMCPRegistry = reg.MCPServers
			anvilCLIRegistry = reg.CLICommands
		}
	}
	if anvilMCPRegistry == nil {
		anvilMCPRegistry = map[string]string{}
	}
	if anvilCLIRegistry == nil {
		anvilCLIRegistry = map[string]string{}
	}
}

func anvilSpoolDir() string {
	dataDir := core.Cfg().GetPath("data_dir")
	if dataDir != "" {
		return filepath.Join(dataDir, "anvil-telemetry")
	}
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".claude", "data", "anvil-telemetry")
}

func anvilSpoolFile() string {
	return filepath.Join(anvilSpoolDir(), "pending.jsonl")
}

func anvilAPIURL() string {
	url := os.Getenv("ANVIL_API")
	if url == "" {
		url = core.Cfg().GetService("anvil_url")
	}
	return url
}

// ---------------------------------------------------------------------------
// Main handler
// ---------------------------------------------------------------------------

func anvilTelemetryHandle(eventType, toolName string, toolInput map[string]any, rawInput string) core.HookResult {
	switch eventType {
	case "SessionStart":
		return anvilSyncPending()
	case "UserPromptSubmit":
		return anvilHandleIntent(rawInput)
	}
	// PostToolUse
	if toolName == "Skill" {
		return anvilHandleSkill(toolInput, rawInput)
	}
	if anvilMCPProxyTools[toolName] {
		return anvilHandleMCP(toolInput, rawInput)
	}
	if toolName == "Bash" {
		return anvilHandleCLI(toolInput, rawInput)
	}
	return core.Allow()
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func anvilIsTest(name string) bool {
	for _, p := range anvilTestPrefixes {
		if strings.HasPrefix(name, p) {
			return true
		}
	}
	if anvilTestExact[name] {
		return true
	}
	return anvilTestDigitsRe.MatchString(name)
}

func anvilParseContext(rawInput string) map[string]any {
	if strings.TrimSpace(rawInput) == "" {
		return map[string]any{}
	}
	var parsed map[string]any
	if err := json.Unmarshal([]byte(rawInput), &parsed); err != nil {
		return map[string]any{}
	}
	if data, ok := parsed["data"].(map[string]any); ok {
		return data
	}
	return parsed
}

func anvilPostToAPI(endpoint string, payload map[string]any) bool {
	base := anvilAPIURL()
	if base == "" {
		return false
	}
	url := base + endpoint
	if !strings.HasPrefix(url, "http://") && !strings.HasPrefix(url, "https://") {
		return false
	}
	data, err := json.Marshal(payload)
	if err != nil {
		return false
	}
	client := &http.Client{Timeout: 3 * time.Second}
	resp, err := client.Post(url, "application/json", strings.NewReader(string(data)))
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	io.Copy(io.Discard, resp.Body)
	return resp.StatusCode == 200 || resp.StatusCode == 201
}

func anvilWriteSpool(payload map[string]any) {
	dir := anvilSpoolDir()
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return
	}
	entry := map[string]any{
		"ts":     time.Now().Format("2006-01-02T15:04:05"),
		"synced": false,
	}
	for k, v := range payload {
		entry[k] = v
	}
	b, err := json.Marshal(entry)
	if err != nil {
		return
	}
	f, err := os.OpenFile(anvilSpoolFile(), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	defer f.Close()
	fmt.Fprintf(f, "%s\n", b)
}

func anvilSend(payload map[string]any) {
	if anvilPostToAPI("/api/anvil/invocations", payload) {
		return
	}
	anvilWriteSpool(payload)
}

// ---------------------------------------------------------------------------
// Channel handlers
// ---------------------------------------------------------------------------

func anvilHandleIntent(rawInput string) core.HookResult {
	matches := anvilCommandNameRe.FindAllStringSubmatch(rawInput, -1)
	if len(matches) == 0 {
		return core.Allow()
	}
	sessionID := ""
	var parsed map[string]any
	if json.Unmarshal([]byte(rawInput), &parsed) == nil {
		data := parsed
		if d, ok := parsed["data"].(map[string]any); ok {
			data = d
		}
		if s, ok := data["session_id"].(string); ok {
			sessionID = s
		}
	}
	for _, m := range matches {
		name := strings.TrimSpace(m[1])
		if anvilCLIBuiltins[name] || anvilIsTest(name) {
			continue
		}
		anvilPostToAPI("/api/anvil/intents", map[string]any{
			"skill_name": name,
			"session_id": sessionID,
		})
	}
	return core.Allow()
}

func anvilHandleSkill(toolInput map[string]any, rawInput string) core.HookResult {
	skillName, _ := toolInput["skill"].(string)
	if skillName == "" || anvilIsTest(skillName) {
		return core.Allow()
	}
	originalName := ""
	if alias, ok := anvilAliasMap[skillName]; ok {
		originalName = skillName
		skillName = alias
	}
	data := anvilParseContext(rawInput)
	toolResponse, _ := data["tool_response"].(map[string]any)
	success := true
	var errMsg interface{}
	if toolResponse != nil {
		if v, ok := toolResponse["success"].(bool); ok {
			success = v
		}
		if e, ok := toolResponse["error"]; ok {
			errMsg = e
		}
	}
	payloadData := map[string]any{
		"args": toolInput["args"],
		"cwd":  data["cwd"],
	}
	if originalName != "" {
		payloadData["original_name"] = originalName
	}
	anvilSend(map[string]any{
		"skill_name":       skillName,
		"session_id":       data["session_id"],
		"agent_model":      data["agent_model"],
		"tool_use_id":      data["tool_use_id"],
		"success":          success,
		"error_message":    errMsg,
		"tool_calls_count": 1,
		"category":         "skill",
		"payload":          payloadData,
	})
	return core.Allow()
}

func anvilHandleMCP(toolInput map[string]any, rawInput string) core.HookResult {
	mcpName, _ := toolInput["name"].(string)
	idx := strings.Index(mcpName, ":")
	if idx < 0 {
		return core.Allow()
	}
	serverName := mcpName[:idx]
	toolName := mcpName[idx+1:]
	station, ok := anvilMCPRegistry[serverName]
	if !ok {
		return core.Allow()
	}
	data := anvilParseContext(rawInput)
	anvilSend(map[string]any{
		"skill_name":       station,
		"session_id":       data["session_id"],
		"agent_model":      data["agent_model"],
		"tool_use_id":      data["tool_use_id"],
		"success":          true,
		"tool_calls_count": 1,
		"category":         "mcp",
		"payload": map[string]any{
			"tool":   toolName,
			"server": serverName,
			"cwd":    data["cwd"],
		},
	})
	return core.Allow()
}

func anvilHandleCLI(toolInput map[string]any, rawInput string) core.HookResult {
	cmd, _ := toolInput["command"].(string)
	cmd = strings.TrimSpace(cmd)
	if cmd == "" {
		return core.Allow()
	}
	tokens := strings.Fields(cmd)
	if len(tokens) == 0 {
		return core.Allow()
	}
	binary := filepath.Base(tokens[0])
	station, ok := anvilCLIRegistry[binary]
	if !ok {
		return core.Allow()
	}
	data := anvilParseContext(rawInput)
	subcommand := ""
	if len(tokens) > 1 {
		subcommand = tokens[1]
	}
	cmdTrunc := cmd
	if len(cmdTrunc) > 200 {
		cmdTrunc = cmdTrunc[:200]
	}
	anvilSend(map[string]any{
		"skill_name":       station,
		"session_id":       data["session_id"],
		"agent_model":      data["agent_model"],
		"tool_use_id":      data["tool_use_id"],
		"success":          true,
		"tool_calls_count": 1,
		"category":         "cli",
		"payload": map[string]any{
			"tool":    subcommand,
			"command": cmdTrunc,
			"cwd":     data["cwd"],
		},
	})
	return core.Allow()
}

func anvilSyncPending() core.HookResult {
	spoolFile := anvilSpoolFile()
	if _, err := os.Stat(spoolFile); os.IsNotExist(err) {
		return core.Allow()
	}
	// Run sync in background goroutine — same pattern as externalSkillTracker
	go anvilSyncPendingInProc()
	return core.Allow()
}

// anvilSyncPendingInProc is the Go in-process port of anvil_telemetry_sync.py.
// Reads pending.jsonl, POSTs unsent entries to Anvil API, moves synced entries
// to synced.jsonl, and rewrites pending.jsonl with only failed entries.
func anvilSyncPendingInProc() {
	spoolFile := anvilSpoolFile()
	raw, err := os.ReadFile(spoolFile)
	if err != nil {
		return
	}

	type spoolEntry = map[string]any

	var allEntries []spoolEntry
	for _, line := range strings.Split(string(raw), "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		var entry spoolEntry
		if json.Unmarshal([]byte(line), &entry) == nil {
			allEntries = append(allEntries, entry)
		}
	}

	if len(allEntries) == 0 {
		return
	}

	base := anvilAPIURL()
	dir := anvilSpoolDir()
	syncedFile := filepath.Join(dir, "synced.jsonl")

	var stillPending []spoolEntry
	var newlySynced []spoolEntry

	client := &http.Client{Timeout: 5 * time.Second}

	for _, entry := range allEntries {
		if synced, _ := entry["synced"].(bool); synced {
			// Already marked synced — move to archive
			newlySynced = append(newlySynced, entry)
			continue
		}

		sent := false
		if base != "" && (strings.HasPrefix(base, "http://") || strings.HasPrefix(base, "https://")) {
			// Build payload matching Python's post_to_anvil()
			payload := map[string]any{
				"skill_name":       entry["skill_name"],
				"session_id":       entry["session_id"],
				"agent_model":      entry["agent_model"],
				"success":          entry["success"],
				"error_message":    entry["error_message"],
				"tool_calls_count": entry["tool_calls_count"],
				"payload":          entry["payload"],
			}
			data, err := json.Marshal(payload)
			if err == nil {
				resp, err := client.Post(base+"/api/anvil/invocations", "application/json", strings.NewReader(string(data)))
				if err == nil {
					io.Copy(io.Discard, resp.Body)
					resp.Body.Close()
					// Match Python _post_to_api: accept both 200 and 201 as success.
					// Otherwise a 200 response would leave entries spooled forever.
					if resp.StatusCode == 200 || resp.StatusCode == 201 {
						sent = true
					}
				}
			}
		}

		if sent {
			entry["synced"] = true
			newlySynced = append(newlySynced, entry)
		} else {
			stillPending = append(stillPending, entry)
		}
	}

	// Append synced entries to archive file
	if len(newlySynced) > 0 {
		if err := os.MkdirAll(dir, 0o755); err == nil {
			sf, err := os.OpenFile(syncedFile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
			if err == nil {
				for _, e := range newlySynced {
					b, _ := json.Marshal(e)
					fmt.Fprintf(sf, "%s\n", b)
				}
				sf.Close()
			}
		}
	}

	// Rewrite pending.jsonl with only unsynced entries
	var pendingLines []string
	for _, e := range stillPending {
		b, _ := json.Marshal(e)
		pendingLines = append(pendingLines, string(b))
	}
	content := ""
	if len(pendingLines) > 0 {
		content = strings.Join(pendingLines, "\n") + "\n"
	}
	_ = os.WriteFile(spoolFile, []byte(content), 0o644)
}
