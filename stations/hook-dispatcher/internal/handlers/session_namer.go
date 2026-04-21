// Package handlers — session_namer.go
// Stop + UserPromptSubmit handler — session auto-namer + color hint.
//
// On the first Stop event of a session, runs a background goroutine (Go in-process) that:
//  1. Reads the session transcript to get the first user message
//  2. Calls Haiku via claude CLI to generate a 2-4 word kebab-case title + color
//  3. Stores in ~/.claude/data/session-titles.json (external registry, file-locked)
//
// On UserPromptSubmit, if a color has been assigned but not yet applied,
// injects a one-time hint so the model can suggest /color <name>.
//
// Non-blocking: spawns goroutine, returns Allow immediately.
// Fail-open: any error -> silently skip, never block Claude Code.
package handlers

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"syscall"
	"time"

	"github.com/joneshong/hook-dispatcher/internal/core"
)

var sessionNamerValidColors = map[string]struct{}{
	"red": {}, "blue": {}, "green": {}, "yellow": {},
	"purple": {}, "orange": {}, "pink": {}, "cyan": {},
}

func init() {
	core.Register("Stop", core.Entry{
		Matcher:    "",
		Handler:    sessionNamerHandle,
		Critical:   false,
		ModuleName: "session_namer",
	})
	core.Register("UserPromptSubmit", core.Entry{
		Matcher:    "",
		Handler:    sessionNamerHandleColorHint,
		Critical:   false,
		ModuleName: "session_namer",
	})
}

// sessionNamerHandle names the session on the first Stop event (non-blocking).
func sessionNamerHandle(_, _ string, _ map[string]any, rawInput string) core.HookResult {
	if os.Getenv("CLAUDE_SESSION_NAMER") == "0" {
		return core.Allow()
	}

	sessionID := os.Getenv("CLAUDE_SESSION_ID")
	if sessionID == "" {
		if strings.TrimSpace(rawInput) != "" {
			var parsed map[string]any
			if err := json.Unmarshal([]byte(rawInput), &parsed); err == nil {
				sessionID, _ = parsed["session_id"].(string)
			}
		}
	}
	if sessionID == "" {
		return core.Allow()
	}

	// Already named? Skip.
	if sessionNamerIsNamed(sessionID) {
		return core.Allow()
	}

	home, _ := os.UserHomeDir()
	// Go in-process — no Python middleman, no fork overhead.
	go sessionNamerRunInProc(sessionID, home)

	return core.Allow()
}

// sessionNamerHandleColorHint injects a one-time color hint on UserPromptSubmit.
func sessionNamerHandleColorHint(_, _ string, _ map[string]any, _ string) core.HookResult {
	if os.Getenv("CLAUDE_SESSION_NAMER") == "0" {
		return core.Allow()
	}

	sessionID := os.Getenv("CLAUDE_SESSION_ID")
	if sessionID == "" {
		return core.Allow()
	}

	marker := fmt.Sprintf("/tmp/.claude-color-hinted-%s", sessionID)
	if _, err := os.Stat(marker); err == nil {
		// Already hinted
		return core.Allow()
	}

	registry := sessionNamerLoadRegistry()
	entry, ok := registry[sessionID]
	if !ok {
		return core.Allow()
	}
	entryMap, ok := entry.(map[string]any)
	if !ok {
		return core.Allow()
	}
	color, _ := entryMap["color"].(string)

	if _, valid := sessionNamerValidColors[color]; !valid || color == "" {
		return core.Allow()
	}

	// Write marker — hint only once per session
	_ = os.WriteFile(marker, []byte(color), 0o644)
	return core.TextResult(fmt.Sprintf("Session color assigned: %s — suggest user run `/color %s`", color, color))
}

func sessionNamerIsNamed(sessionID string) bool {
	registry := sessionNamerLoadRegistry()
	_, exists := registry[sessionID]
	return exists
}

func sessionNamerLoadRegistry() map[string]any {
	home, _ := os.UserHomeDir()
	registryPath := filepath.Join(home, ".claude", "data", "session-titles.json")
	data, err := os.ReadFile(registryPath)
	if err != nil {
		return map[string]any{}
	}
	var registry map[string]any
	if err := json.Unmarshal(data, &registry); err != nil {
		return map[string]any{}
	}
	return registry
}

// sessionNamerRunInProc is the Go in-process replacement for sessionNamerBuildCode.
// Previously this logic was inlined as Python and executed via `python3 -c <code>`.
// Now it runs directly in a goroutine — no Python fork overhead.
//
// Steps (mirrors the Python inline worker exactly):
//  1. glob ~/.claude/projects/**/{sessionID}.jsonl → find transcript
//  2. read transcript → extract first user message text
//  3. build prompt → exec claude CLI (haiku) → parse JSON response
//  4. write title+color to ~/.claude/data/session-titles.json with syscall.Flock
func sessionNamerRunInProc(sessionID, home string) {
	registryPath := filepath.Join(home, ".claude", "data", "session-titles.json")

	// 1. Find transcript via glob
	pattern := filepath.Join(home, ".claude", "projects", "**", sessionID+".jsonl")
	matches, err := filepath.Glob(pattern)
	if err != nil || len(matches) == 0 {
		// filepath.Glob doesn't support ** — use Walk instead
		transcriptPath := sessionNamerFindTranscript(home, sessionID)
		if transcriptPath == "" {
			return
		}
		matches = []string{transcriptPath}
	}

	// 2. Extract first user message from transcript
	firstMessage := sessionNamerExtractFirstUserMessage(matches[0])
	if strings.TrimSpace(firstMessage) == "" {
		return
	}
	if len(firstMessage) > 500 {
		firstMessage = firstMessage[:500]
	}

	// 3. Call Haiku via claude CLI
	prompt := "Generate a session title and pick a prompt-bar color.\n" +
		"Title: 2-4 word kebab-case, verb-first, max 30 chars.\n" +
		"Color: pick ONE from [red,blue,green,yellow,purple,orange,pink,cyan] " +
		"that matches the task mood/domain.\n" +
		"Return ONLY JSON: {\"title\":\"...\",\"color\":\"...\"}\n\n" +
		"User message: " + firstMessage

	env := os.Environ()
	// Suppress recursion + context supervisor overhead
	env = sessionNamerReplaceEnv(env, "CTX_SUPERVISOR_LEVEL", "off")
	env = sessionNamerReplaceEnv(env, "CLAUDE_SESSION_NAMER", "0")

	r := core.RunCmdWithEnv(
		[]string{"claude", "-p", prompt, "--model", "haiku", "--output-format", "text", "--no-session-persistence"},
		"", 120*time.Second, "", env,
	)
	if r == nil || r.ExitCode != 0 {
		return
	}

	raw := strings.TrimSpace(r.Stdout)
	if raw == "" {
		return
	}

	// Extract JSON object from response (may have preamble text)
	jsonPat := regexp.MustCompile(`\{[^}]*"title"[^}]*\}`)
	if m := jsonPat.FindString(raw); m != "" {
		raw = m
	}

	var parsed struct {
		Title string `json:"title"`
		Color string `json:"color"`
	}
	title := ""
	color := ""
	if err := json.Unmarshal([]byte(raw), &parsed); err == nil {
		title = strings.TrimSpace(parsed.Title)
		color = strings.ToLower(strings.TrimSpace(parsed.Color))
	} else {
		title = strings.TrimSpace(raw)
	}
	if _, valid := sessionNamerValidColors[color]; !valid {
		color = ""
	}
	if title == "" {
		return
	}

	// 4. Write to registry with file lock (mirrors fcntl.flock in Python)
	if err := os.MkdirAll(filepath.Dir(registryPath), 0o755); err != nil {
		return
	}
	f, err := os.OpenFile(registryPath, os.O_RDWR|os.O_CREATE, 0o644)
	if err != nil {
		return
	}
	defer f.Close()

	// Exclusive lock — mirrors fcntl.LOCK_EX
	if err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX); err != nil {
		return
	}
	defer syscall.Flock(int(f.Fd()), syscall.LOCK_UN) //nolint:errcheck

	// Read existing registry
	registry := map[string]any{}
	info, _ := f.Stat()
	if info != nil && info.Size() > 0 {
		data, _ := os.ReadFile(registryPath)
		if len(data) > 0 {
			_ = json.Unmarshal(data, &registry)
		}
	}

	// Python datetime.now(UTC).isoformat() emits "+00:00"; match that
	// instead of Go's default "Z" so string comparisons match registry
	// entries written by legacy Python code paths.
	createdAt := time.Now().UTC().Format("2006-01-02T15:04:05-07:00")
	registry[sessionID] = map[string]any{
		"title":      title,
		"color":      color,
		"created_at": createdAt,
	}

	out, err := json.MarshalIndent(registry, "", "  ")
	if err != nil {
		return
	}

	if err := f.Truncate(0); err != nil {
		return
	}
	if _, err := f.Seek(0, 0); err != nil {
		return
	}
	_, _ = f.Write(out)
}

// sessionNamerFindTranscript walks ~/.claude/projects/ to find {sessionID}.jsonl.
// filepath.Glob does not support **, so we use filepath.WalkDir.
func sessionNamerFindTranscript(home, sessionID string) string {
	projectsDir := filepath.Join(home, ".claude", "projects")
	target := sessionID + ".jsonl"
	found := ""
	errStop := fmt.Errorf("stop")
	_ = filepath.WalkDir(projectsDir, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		if d.Name() == target {
			found = path
			return errStop // short-circuit
		}
		return nil
	})
	return found
}

// sessionNamerExtractFirstUserMessage reads the JSONL transcript and returns
// the text content of the first user message.
func sessionNamerExtractFirstUserMessage(transcriptPath string) string {
	f, err := os.Open(transcriptPath)
	if err != nil {
		return ""
	}
	defer f.Close()

	scanner := bufio.NewScanner(f)
	scanner.Buffer(make([]byte, 1024*1024), 1024*1024)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		var entry map[string]any
		if err := json.Unmarshal([]byte(line), &entry); err != nil {
			continue
		}
		// Determine role: entry.type == "user" or message.role == "user"
		msgObj, _ := entry["message"].(map[string]any)
		role, _ := entry["type"].(string)
		if role == "" && msgObj != nil {
			role, _ = msgObj["role"].(string)
		}
		if role != "user" {
			continue
		}
		if msgObj == nil {
			continue
		}
		content := msgObj["content"]
		switch c := content.(type) {
		case string:
			if strings.TrimSpace(c) != "" {
				return c
			}
		case []any:
			for _, block := range c {
				bMap, ok := block.(map[string]any)
				if !ok {
					continue
				}
				if bMap["type"] == "text" {
					if text, ok := bMap["text"].(string); ok && strings.TrimSpace(text) != "" {
						return text
					}
				}
			}
		}
	}
	return ""
}

// sessionNamerReplaceEnv replaces or appends a key=value in an os.Environ() slice.
func sessionNamerReplaceEnv(env []string, key, value string) []string {
	prefix := key + "="
	for i, e := range env {
		if strings.HasPrefix(e, prefix) {
			env[i] = prefix + value
			return env
		}
	}
	return append(env, prefix+value)
}
