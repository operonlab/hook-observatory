package handlers

// external.go — Go port of handlers/external.py
//
// Wraps four sub-handlers that call external scripts:
//   - recall        → UserPromptSubmit  (memvault recall)
//   - skill_tracker → PostToolUse/Skill (skill usage tracker) [Go in-process]
//   - progressive_extract → PreCompact  (fire-and-forget extraction) [stdin-pipe optimised]
//   - sync_login    → SessionStart      (Playwright profile sync)
//
// All are deferrable. Any error → fail-open (core.Allow()).

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/joneshong/hook-dispatcher/internal/core"
	portregistry "github.com/joneshong/hook-dispatcher/internal/portregistry"
)

// recallEndpoint is the Core API URL for server-side recall text building.
// Replaces the former fork of ~/workshop/mcp/memvault/scripts/recall.py.
// Resolved from the cross-language port registry (core = 10000).
var recallEndpoint = portregistry.URL("core", "/api/memvault/recall/text", 10000)

func init() {
	core.Register("UserPromptSubmit", core.Entry{
		Matcher:    "",
		Handler:    externalRecall,
		Critical:   false,
		ModuleName: "external",
	})
	core.Register("PostToolUse", core.Entry{
		Matcher:    "Skill",
		Handler:    externalSkillTracker,
		Critical:   false,
		ModuleName: "external",
	})
	core.Register("PreCompact", core.Entry{
		Matcher:    "",
		Handler:    externalProgressiveExtract,
		Critical:   false,
		ModuleName: "external",
	})
	core.Register("SessionStart", core.Entry{
		Matcher:    "",
		Handler:    externalSyncLogin,
		Critical:   false,
		ModuleName: "external",
	})
}

func memvaultScripts() string {
	home, _ := os.UserHomeDir()
	return filepath.Join(home, "workshop", "mcp", "memvault", "scripts")
}

// externalRecall POSTs the hook stdin payload to Core's recall/text endpoint
// and injects the returned markdown into the UserPromptSubmit passthrough.
//
// The old Python version forked `python3 recall.py` and piped stdin; that
// logic now lives server-side in core/src/modules/memvault/recall_text.
// Any error is fail-open (core.Allow()).
func externalRecall(_, _ string, _ map[string]any, rawInput string) core.HookResult {
	if strings.TrimSpace(rawInput) == "" {
		return core.Allow()
	}
	client := &http.Client{Timeout: 15 * time.Second}
	resp, err := client.Post(recallEndpoint, "application/json", strings.NewReader(rawInput))
	if err != nil {
		return core.Allow()
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		_, _ = io.Copy(io.Discard, resp.Body)
		return core.Allow()
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil || len(bytes.TrimSpace(body)) == 0 {
		return core.Allow()
	}
	return core.TextResult(string(body))
}

// externalSkillTracker is a Go in-process port of skill_tracker.py.
//
// Triggered as PostToolUse/Skill. Reads rawInput JSON, checks for "Skill" in
// tool_name (matched upstream by Matcher, but we re-check for safety), extracts
// skill metadata, POSTs to Core API, and falls back to JSONL on failure.
// If the skill is a "knowledge skill" and the response body > 200 chars we
// also POST a memory block.
func externalSkillTracker(_, _ string, _ map[string]any, rawInput string) core.HookResult {
	go skillTrackerInProc(rawInput)
	return core.Allow()
}

// ---------------------------------------------------------------------------
// skill_tracker in-process implementation
// ---------------------------------------------------------------------------

const skillTrackerSpaceID = "default"

// skillTrackerCoreAPI is resolved from the cross-language port registry
// (core = 10000) at package init.
var skillTrackerCoreAPI = portregistry.URL("core", "", 10000)

var skillTrackerKnowledgeSkills = map[string]bool{
	"smart-search":      true,
	"company-intel":     true,
	"competitive-intel": true,
	"content-writer":    true,
	"brainstorming":     true,
	"meeting-insights":  true,
}

func skillTrackerInProc(rawInput string) {
	// Parse stdin JSON
	var input map[string]any
	if err := json.Unmarshal([]byte(rawInput), &input); err != nil {
		return
	}

	// Filter: only process Skill tool calls (Matcher already filtered, belt-and-suspenders)
	toolName, _ := input["tool_name"].(string)
	if !strings.Contains(toolName, "Skill") {
		return
	}

	// Extract fields
	toolInput, _ := input["tool_input"].(map[string]any)
	skillName := skillTrackerExtractName(toolInput)
	sessionID, _ := input["session_id"].(string)
	cwd, _ := input["cwd"].(string)
	invokedAt := time.Now().UTC().Format("2006-01-02T15:04:05Z")

	// Detect outcome from tool_response
	rawResponse := ""
	if tr := input["tool_response"]; tr != nil {
		if b, err := json.Marshal(tr); err == nil {
			rawResponse = string(b)
		}
	}
	rawResponseLower := strings.ToLower(rawResponse)
	outcome := "success"
	if strings.Contains(rawResponseLower, "error") || strings.Contains(rawResponseLower, "failed") {
		outcome = "failure"
	}

	skillTrackerLog(fmt.Sprintf("skill='%s' session='%s' outcome='%s'", skillName, sessionID, outcome))

	// Build POST body
	postBody := map[string]any{
		"skill_name":     skillName,
		"source_session": sessionID,
		"cwd":            cwd,
		"invoked_at":     invokedAt,
		"outcome":        outcome,
		"duration_ms":    nil,
	}
	bodyBytes, err := json.Marshal(postBody)
	if err != nil {
		skillTrackerLog("ERROR: failed to build POST body")
		return
	}

	// Primary: POST to Core API
	status := skillTrackerPost(
		skillTrackerCoreAPI+"/api/memvault/kg/skills/invoke?space_id="+skillTrackerSpaceID,
		bodyBytes, 5*time.Second,
	)

	if status == 201 {
		skillTrackerLog(fmt.Sprintf("API OK (201) skill='%s'", skillName))

		// Knowledge Flywheel: capture skill output as memory block
		if skillTrackerKnowledgeSkills[skillName] {
			cleanResp := rawResponse
			if len(cleanResp) > 2000 {
				cleanResp = cleanResp[:2000]
			}
			if len(cleanResp) > 200 {
				topicPreview := cleanResp
				if len(topicPreview) > 80 {
					topicPreview = topicPreview[:80]
				}
				topicPreview = strings.ReplaceAll(topicPreview, "\n", " ")

				blockBody := map[string]any{
					"topic":      fmt.Sprintf("skill:%s — %s", skillName, topicPreview),
					"content":    cleanResp,
					"block_type": "skill_knowledge",
					"tags":       []string{"skill:" + skillName, "auto-captured", "knowledge-flywheel"},
					"source":     "skill-tracker",
				}
				if blockBytes, err := json.Marshal(blockBody); err == nil {
					blockStatus := skillTrackerPost(
						skillTrackerCoreAPI+"/api/memvault/blocks?space_id="+skillTrackerSpaceID,
						blockBytes, 5*time.Second,
					)
					if blockStatus == 201 {
						skillTrackerLog(fmt.Sprintf("Knowledge captured for skill='%s' (%d chars)", skillName, len(cleanResp)))
					} else {
						skillTrackerLog(fmt.Sprintf("Knowledge capture failed (HTTP %d) for skill='%s'", blockStatus, skillName))
					}
				}
			} else {
				skillTrackerLog(fmt.Sprintf("Skipping knowledge capture — response too short (%d chars)", len(cleanResp)))
			}
		}
		return
	}

	skillTrackerLog(fmt.Sprintf("API FAIL (status=%d), writing to fallback JSONL", status))

	// Fallback: JSONL
	home, _ := os.UserHomeDir()
	fallbackFile := filepath.Join(home, "Claude", "memvault", "skill-invocations.jsonl")
	fallbackRecord := map[string]any{
		"skill_name":     skillName,
		"source_session": sessionID,
		"cwd":            cwd,
		"invoked_at":     invokedAt,
		"outcome":        outcome,
		"duration_ms":    nil,
		"ingested":       false,
	}
	if recBytes, err := json.Marshal(fallbackRecord); err == nil {
		if err2 := os.MkdirAll(filepath.Dir(fallbackFile), 0o755); err2 == nil {
			if f, err3 := os.OpenFile(fallbackFile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644); err3 == nil {
				defer f.Close()
				fmt.Fprintf(f, "%s\n", recBytes)
				skillTrackerLog(fmt.Sprintf("JSONL written skill='%s'", skillName))
			}
		}
	}
}

// skillTrackerExtractName tries multiple field names to find the skill name.
func skillTrackerExtractName(toolInput map[string]any) string {
	if toolInput == nil {
		return "unknown"
	}
	for _, key := range []string{"skill_name", "name"} {
		if v, ok := toolInput[key].(string); ok && v != "" {
			return v
		}
	}
	// First string value fallback
	for _, v := range toolInput {
		if s, ok := v.(string); ok && s != "" {
			return s
		}
	}
	return "unknown"
}

// skillTrackerPost sends a JSON POST and returns the HTTP status code (0 on error).
func skillTrackerPost(url string, body []byte, timeout time.Duration) int {
	client := &http.Client{Timeout: timeout}
	resp, err := client.Post(url, "application/json", bytes.NewReader(body))
	if err != nil {
		return 0
	}
	defer resp.Body.Close()
	return resp.StatusCode
}

// skillTrackerLog appends a timestamped line to the skill-tracker log.
func skillTrackerLog(msg string) {
	home, _ := os.UserHomeDir()
	logFile := filepath.Join(home, "Claude", "memvault", "logs", "skill-tracker.log")
	if err := os.MkdirAll(filepath.Dir(logFile), 0o755); err != nil {
		return
	}
	ts := time.Now().Format("15:04:05")
	line := fmt.Sprintf("[skill-tracker] %s %s\n", ts, msg)
	if f, err := os.OpenFile(logFile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644); err == nil {
		defer f.Close()
		_, _ = f.WriteString(line)
	}
}

// externalProgressiveExtract runs the progressive extraction in-process (Go goroutine).
// Previously this spawned a Python subprocess via: sh -c "cat tmpfile | python3 extract_progressive.py"
// Now it runs entirely in Go — same logic, no Python fork, no temp file, no shell overhead.
func externalProgressiveExtract(_, _ string, _ map[string]any, rawInput string) core.HookResult {
	go progressiveExtractInProc(rawInput)
	return core.Allow()
}

// ---------------------------------------------------------------------------
// extract_progressive in-process implementation
// Mirrors ~/workshop/mcp/memvault/scripts/extract_progressive.py (303 lines)
// ---------------------------------------------------------------------------

func progressiveExtractInProc(rawInput string) {
	home, _ := os.UserHomeDir()
	logDir := filepath.Join(home, "Claude", "memvault", "logs")
	_ = os.MkdirAll(logDir, 0o755)
	logFile := filepath.Join(logDir, "progressive.log")

	progressiveLog := func(msg string) {
		ts := time.Now().Format("2006-01-02 15:04:05")
		line := fmt.Sprintf("[progressive] %s %s\n", ts, msg)
		fmt.Fprint(os.Stderr, line)
		if f, err := os.OpenFile(logFile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644); err == nil {
			_, _ = f.WriteString(line)
			f.Close()
		}
	}

	// 1. Parse stdin JSON
	var input map[string]any
	if err := json.Unmarshal([]byte(rawInput), &input); err != nil {
		progressiveLog(fmt.Sprintf("Invalid JSON input: %v", err))
		return
	}

	sessionID, _ := input["session_id"].(string)
	transcriptPath, _ := input["transcript_path"].(string)
	trigger, _ := input["trigger"].(string)
	if trigger == "" {
		trigger = "unknown"
	}
	sessionID = strings.TrimSpace(sessionID)
	transcriptPath = strings.TrimSpace(transcriptPath)

	if sessionID == "" || transcriptPath == "" {
		progressiveLog("Missing session_id or transcript_path, skipping.")
		return
	}

	if _, err := os.Stat(transcriptPath); err != nil {
		progressiveLog(fmt.Sprintf("Transcript not found: %s", transcriptPath))
		return
	}

	progressiveLog(fmt.Sprintf("PreCompact trigger=%s session=%s", trigger, sessionID))

	// 2. Read transcript — lightweight (text only, no tool results)
	conversationLines, lineCount, err := progressiveReadTranscript(transcriptPath)
	if err != nil {
		progressiveLog(fmt.Sprintf("Error reading transcript: %v", err))
		return
	}
	if lineCount < 4 {
		progressiveLog(fmt.Sprintf("Only %d messages, too short for progressive extraction.", lineCount))
		return
	}

	// 3. Load prior progressive state
	progressiveDir := filepath.Join(home, "Claude", "memvault", "progressive")
	_ = os.MkdirAll(progressiveDir, 0o755)
	stateFile := filepath.Join(progressiveDir, sessionID+".json")

	type progressiveState struct {
		SessionID       string   `json:"session_id"`
		LineCount       int      `json:"line_count"`
		Observations    []string `json:"observations"`
		UpdatedAt       string   `json:"updated_at"`
		CompactionCount int      `json:"compaction_count"`
	}

	var priorState *progressiveState
	priorLineCount := 0
	if data, err := os.ReadFile(stateFile); err == nil {
		var ps progressiveState
		if err := json.Unmarshal(data, &ps); err == nil {
			priorState = &ps
			priorLineCount = ps.LineCount
		}
	}

	newLines := lineCount - priorLineCount
	if newLines < 4 {
		progressiveLog(fmt.Sprintf("Only %d new messages since last progressive, skipping.", newLines))
		return
	}

	// 4. Build progressive prompt (mirrors Python prompt exactly)
	conversation := strings.Join(conversationLines, "\n")
	// Truncate to 30K chars (take tail — most recent content)
	if len(conversation) > 30000 {
		conversation = conversation[len(conversation)-30000:]
		if nl := strings.Index(conversation, "\n"); nl != -1 {
			conversation = conversation[nl+1:]
		}
	}

	priorObservations := ""
	if priorState != nil && len(priorState.Observations) > 0 {
		var obs []string
		for _, o := range priorState.Observations {
			obs = append(obs, "- "+o)
		}
		priorObservations = strings.Join(obs, "\n")
	}

	priorSection := ""
	if priorObservations != "" {
		priorSection = "\n## 先前已記錄的觀察（不要重複這些）\n" + priorObservations
	}

	prompt := "你是對話記憶的中途快照員。這是一個進行中的 Claude Code session，即將壓縮對話。\n" +
		"在壓縮前，快速記錄到目前為止值得記住的觀察點。\n\n" +
		"## 任務\n" +
		"從對話中提煉 3-8 個簡短觀察（每條 1-2 句話）。聚焦：\n" +
		"1. 使用者做了什麼技術決策？為什麼？\n" +
		"2. 遇到了什麼問題？如何解決？\n" +
		"3. 使用者表達了什麼偏好？\n\n" +
		"## 規則\n" +
		"- 每條觀察精簡有力（不超過 80 字）\n" +
		"- 保留具體的：檔案路徑、函數名、版本號、指令\n" +
		"- 不要重複已有的觀察\n" +
		"- 如果沒有值得記住的內容，回傳 {\"skip\": true}\n" +
		priorSection + "\n\n" +
		"## 輸出格式（JSON，不加 code fence）\n" +
		"{\n" +
		"  \"observations\": [\n" +
		"    \"觀察 1：具體的技術發現或決策\",\n" +
		"    \"觀察 2：遇到的問題和解法\"\n" +
		"  ]\n" +
		"}\n\n" +
		"---\n\n" +
		"對話（到目前為止）：\n\n" +
		conversation

	// 5. Call LLM via claude CLI
	progressiveModel := os.Getenv("MEMVAULT_PROGRESSIVE_MODEL")
	if progressiveModel == "" {
		progressiveModel = "haiku"
	}
	progressiveLog(fmt.Sprintf("Calling Claude (%s) for progressive extraction ...", progressiveModel))

	env := os.Environ()
	// Remove CLAUDECODE to avoid recursion; skip recall to prevent loop
	filteredEnv := env[:0]
	for _, e := range env {
		if strings.HasPrefix(e, "CLAUDECODE=") {
			continue
		}
		filteredEnv = append(filteredEnv, e)
	}
	filteredEnv = sessionNamerReplaceEnv(filteredEnv, "MEMVAULT_SKIP_RECALL", "1")
	// Suppress voicenotify TTS in the spawned `claude -p` sub-session — its
	// Stop hook would otherwise read the system-prompt opening
	// ("你是對話記憶的中途快照員 …") aloud as the master pane's task summary.
	filteredEnv = sessionNamerReplaceEnv(filteredEnv, "CLAUDE_VOICE", "0")

	t0 := time.Now()
	r := core.RunCmdWithEnv(
		[]string{"claude", "-p", "--model", progressiveModel},
		prompt, 60*time.Second, "", filteredEnv,
	)
	elapsed := time.Since(t0)

	if r == nil || r.ExitCode != 0 {
		progressiveLog(fmt.Sprintf("Claude call failed (exit %d) in %.1fs.", func() int {
			if r == nil {
				return -1
			}
			return r.ExitCode
		}(), elapsed.Seconds()))
		return
	}

	output := strings.TrimSpace(r.Stdout)
	progressiveLog(fmt.Sprintf("Claude returned in %.1fs (%d chars).", elapsed.Seconds(), len(output)))

	if output == "" {
		progressiveLog("Empty response, skipping.")
		return
	}

	// 6. Strip code fences
	if strings.HasPrefix(output, "```") {
		lines := strings.Split(output, "\n")
		if len(lines) > 0 && strings.HasPrefix(lines[0], "```") {
			lines = lines[1:]
		}
		if len(lines) > 0 && strings.TrimSpace(lines[len(lines)-1]) == "```" {
			lines = lines[:len(lines)-1]
		}
		output = strings.Join(lines, "\n")
	}

	// 7. Extract JSON
	jsonStart := strings.Index(output, "{")
	jsonEnd := strings.LastIndex(output, "}") + 1
	if jsonStart == -1 || jsonEnd <= jsonStart {
		progressiveLog("No JSON found in response.")
		return
	}
	jsonStr := output[jsonStart:jsonEnd]

	var data struct {
		Skip         bool     `json:"skip"`
		Observations []string `json:"observations"`
	}
	if err := json.Unmarshal([]byte(jsonStr), &data); err != nil {
		progressiveLog(fmt.Sprintf("JSON parse failed: %v", err))
		return
	}

	if data.Skip {
		progressiveLog("LLM says skip — nothing worth noting.")
		return
	}
	if len(data.Observations) == 0 {
		progressiveLog("No observations returned.")
		return
	}

	// 8. Merge with prior observations, cap at 20
	var allObs []string
	if priorState != nil {
		allObs = append(allObs, priorState.Observations...)
	}
	allObs = append(allObs, data.Observations...)
	if len(allObs) > 20 {
		allObs = allObs[len(allObs)-20:]
	}

	compactionCount := 1
	if priorState != nil {
		compactionCount = priorState.CompactionCount + 1
	}

	newState := progressiveState{
		SessionID:       sessionID,
		LineCount:       lineCount,
		Observations:    allObs,
		UpdatedAt:       time.Now().UTC().Format("2006-01-02T15:04:05Z"),
		CompactionCount: compactionCount,
	}

	stateBytes, err := json.MarshalIndent(newState, "", "  ")
	if err != nil {
		progressiveLog(fmt.Sprintf("Failed to marshal state: %v", err))
		return
	}
	if err := os.WriteFile(stateFile, stateBytes, 0o644); err != nil {
		progressiveLog(fmt.Sprintf("Failed to save state: %v", err))
		return
	}

	priorCount := 0
	if priorState != nil {
		priorCount = len(priorState.Observations)
	}
	progressiveLog(fmt.Sprintf("Saved %d new + %d prior = %d total observations.",
		len(data.Observations), priorCount, len(allObs)))
}

// progressiveReadTranscript reads a JSONL transcript and returns conversation lines
// and total message count. Mirrors Python's transcript reading loop.
func progressiveReadTranscript(transcriptPath string) ([]string, int, error) {
	f, err := os.Open(transcriptPath)
	if err != nil {
		return nil, 0, err
	}
	defer f.Close()

	var lines []string
	lineCount := 0

	scanner := bufio.NewScanner(f)
	scanner.Buffer(make([]byte, 2*1024*1024), 2*1024*1024)
	for scanner.Scan() {
		raw := strings.TrimSpace(scanner.Text())
		if raw == "" {
			continue
		}
		var entry map[string]any
		if err := json.Unmarshal([]byte(raw), &entry); err != nil {
			continue
		}
		entryType, _ := entry["type"].(string)
		if entryType != "user" && entryType != "assistant" {
			continue
		}
		message, _ := entry["message"].(map[string]any)
		if message == nil {
			continue
		}
		content := message["content"]
		lineCount++

		role := "USER"
		if entryType == "assistant" {
			role = "ASSISTANT"
		}

		switch c := content.(type) {
		case string:
			if strings.TrimSpace(c) != "" {
				lines = append(lines, role+": "+c)
			}
		case []any:
			var parts []string
			for _, item := range c {
				itemMap, ok := item.(map[string]any)
				if !ok {
					continue
				}
				itemType, _ := itemMap["type"].(string)
				switch itemType {
				case "text":
					if text, ok := itemMap["text"].(string); ok && strings.TrimSpace(text) != "" {
						parts = append(parts, text)
					}
				case "thinking":
					if text, ok := itemMap["text"].(string); ok && strings.TrimSpace(text) != "" && len(text) > 100 {
						if len(text) > 1000 {
							text = text[:1000]
						}
						parts = append(parts, "[THINKING] "+text)
					}
				}
			}
			if len(parts) > 0 {
				lines = append(lines, role+": "+strings.Join(parts, "\n"))
			}
		}
	}
	return lines, lineCount, scanner.Err()
}

// externalSyncLogin runs ~/.playwright-profiles/sync-login.sh --hook.
func externalSyncLogin(_, _ string, _ map[string]any, rawInput string) core.HookResult {
	home, _ := os.UserHomeDir()
	script := filepath.Join(home, ".playwright-profiles", "sync-login.sh")
	if _, err := os.Stat(script); err != nil {
		return core.Allow()
	}
	r := core.RunCmd([]string{script, "--hook"}, rawInput, 15*time.Second, "")
	if r == nil || r.ExitCode != 0 {
		return core.Allow()
	}
	return core.Allow()
}

// --- helpers -----------------------------------------------------------------

// pythonBin returns the canonical python3 path for this workshop.
func pythonBin() string {
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".local", "bin", "python3")
}

// shellQuote wraps s in single quotes, escaping any embedded single quotes.
func shellQuote(s string) string {
	result := "'"
	for _, ch := range s {
		if ch == '\'' {
			result += "'\\''"
		} else {
			result += string(ch)
		}
	}
	result += "'"
	return result
}
