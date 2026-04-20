package handlers

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/joneshong/hook-dispatcher/internal/core"
)

func init() {
	core.Register("SubagentStop", core.Entry{
		Handler:    verifyCompletionHandle,
		ModuleName: "verify_completion",
	})
}

var (
	vcCodeAgents = map[string]bool{
		"worker":             true,
		"designer":           true,
		"foreman":            true,
		"codex-dispatcher":   true,
		"gemini-dispatcher":  true,
		"copilot-dispatcher": true,
	}
	vcSkipAgents = map[string]bool{
		"explorer":          true,
		"Explore":           true,
		"Plan":              true,
		"researcher":        true,
		"reviewer":          true,
		"browser":           true,
		"media":             true,
		"claude-code-guide": true,
		"writer":            true,
		"statusline-setup":  true,
	}
)

const (
	vcDefaultMaxIter    = 5
	vcDefaultTimeoutMin = 30
	vcCmdTimeout        = 60 * time.Second
)

// ---------------------------------------------------------------------------
// Main handler
// ---------------------------------------------------------------------------

func verifyCompletionHandle(eventType, _ string, _ map[string]any, rawInput string) core.HookResult {
	if eventType != "SubagentStop" {
		return core.Allow()
	}

	var data map[string]any
	if strings.TrimSpace(rawInput) != "" {
		_ = json.Unmarshal([]byte(rawInput), &data)
	}
	if data == nil {
		data = map[string]any{}
	}

	agentType, _ := data["agent_type"].(string)
	if agentType == "" {
		agentType, _ = data["subagent_type"].(string)
	}
	agentID, _ := data["agent_id"].(string)
	if agentID == "" {
		agentID = "unknown"
	}
	sessionID, _ := data["session_id"].(string)
	if sessionID == "" {
		sessionID = "unknown"
	}
	cwd, _ := data["cwd"].(string)
	if cwd == "" {
		cwd, _ = os.Getwd()
	}

	// Skip non-code agents
	if vcSkipAgents[agentType] {
		return core.Allow()
	}
	if agentType != "" && !vcCodeAgents[agentType] {
		return core.Allow()
	}

	root := vcFindProjectRoot(cwd)
	config := vcFindVerifyConfig(cwd, root)
	if config == nil {
		return core.Allow()
	}

	commands, _ := config["commands"].([]string)
	if len(commands) == 0 {
		return core.Allow()
	}

	maxIter := vcDefaultMaxIter
	if v, ok := config["max_iterations"].(int); ok {
		maxIter = v
	}
	timeoutMin := vcDefaultTimeoutMin
	if v, ok := config["timeout_minutes"].(int); ok {
		timeoutMin = v
	}

	sp := vcStatePath(sessionID, agentID)
	state := vcLoadState(sp)
	if state == nil {
		state = map[string]any{
			"iteration":  float64(0),
			"started_at": float64(time.Now().Unix()),
			"agent_id":   agentID,
		}
	}

	// JSON numbers always decode as float64; be defensive for fresh state too.
	startedAt := asFloat64(state["started_at"])
	iteration := int(asFloat64(state["iteration"]))

	elapsedMin := time.Since(time.Unix(int64(startedAt), 0)).Minutes()

	if iteration >= maxIter {
		vcCleanupState(sp)
		return core.Message(fmt.Sprintf(
			"[verify-completion] Max iterations (%d) reached. Allowing completion — please review manually.", maxIter,
		))
	}
	if elapsedMin > float64(timeoutMin) {
		vcCleanupState(sp)
		return core.Message(fmt.Sprintf(
			"[verify-completion] Timeout (%dmin) reached. Allowing completion — please review manually.", timeoutMin,
		))
	}

	results := vcRunVerify(commands, root)
	allPassed := true
	for _, r := range results {
		if !r.passed {
			allPassed = false
			break
		}
	}

	if allPassed {
		vcCleanupState(sp)
		return core.Allow()
	}

	iteration++
	state["iteration"] = float64(iteration)
	vcSaveState(sp, state)

	var reportLines []string
	var failed []vcResult
	for _, r := range results {
		if !r.passed {
			failed = append(failed, r)
		}
	}
	reportLines = append(reportLines, fmt.Sprintf(
		"[verify-completion] Iteration %d/%d — %d command(s) failed:", iteration, maxIter, len(failed),
	))
	for _, r := range failed {
		reportLines = append(reportLines, fmt.Sprintf("\n--- FAIL: %s ---", r.cmd))
		if r.output != "" {
			reportLines = append(reportLines, r.output)
		}
	}
	reportLines = append(reportLines, fmt.Sprintf(
		"\nFix the issues and try again. (%d attempts remaining)", maxIter-iteration,
	))

	return core.Block(strings.Join(reportLines, "\n"))
}

// ---------------------------------------------------------------------------
// Config discovery
// ---------------------------------------------------------------------------

type vcResult struct {
	cmd    string
	passed bool
	output string
}

func vcFindProjectRoot(cwd string) string {
	r := core.RunCmd([]string{"git", "rev-parse", "--show-toplevel"}, "", 5*time.Second, cwd)
	if r != nil && r.ExitCode == 0 {
		return strings.TrimSpace(r.Stdout)
	}
	return cwd
}

func vcFindVerifyConfig(cwd, root string) map[string]any {
	// Priority 1: .verify.json
	searchDirs := []string{cwd}
	if cwd != root {
		searchDirs = append(searchDirs, root)
	}
	for _, dir := range searchDirs {
		path := filepath.Join(dir, ".verify.json")
		data, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		var raw map[string]any
		if err := json.Unmarshal(data, &raw); err != nil {
			continue
		}
		if cmds := vcExtractCommands(raw); len(cmds) > 0 {
			out := map[string]any{"commands": cmds}
			if v, ok := raw["max_iterations"].(float64); ok {
				out["max_iterations"] = int(v)
			}
			if v, ok := raw["timeout_minutes"].(float64); ok {
				out["timeout_minutes"] = int(v)
			}
			return out
		}
	}

	// Priority 2: auto-detect
	cmds := vcAutoDetect(root)
	if len(cmds) > 0 {
		return map[string]any{"commands": cmds, "_auto_detected": true}
	}
	return nil
}

func vcExtractCommands(raw map[string]any) []string {
	cmdsRaw, ok := raw["commands"].([]any)
	if !ok {
		return nil
	}
	var cmds []string
	for _, c := range cmdsRaw {
		if s, ok := c.(string); ok {
			cmds = append(cmds, s)
		}
	}
	return cmds
}

func vcAutoDetect(root string) []string {
	var commands []string

	// Python: pyproject.toml with ruff
	pyproject := filepath.Join(root, "pyproject.toml")
	if data, err := os.ReadFile(pyproject); err == nil {
		content := string(data)
		if strings.Contains(content, "[tool.ruff]") || strings.Contains(content, "ruff") {
			commands = append(commands, "ruff check . --quiet")
		}
	}

	// Node: package.json
	pkgJSON := filepath.Join(root, "package.json")
	if data, err := os.ReadFile(pkgJSON); err == nil {
		var pkg map[string]any
		if json.Unmarshal(data, &pkg) == nil {
			scripts, _ := pkg["scripts"].(map[string]any)
			pm := vcDetectPackageManager(root)
			if _, ok := scripts["lint"]; ok {
				commands = append(commands, pm+" run lint")
			}
			if _, ok := scripts["typecheck"]; ok {
				commands = append(commands, pm+" run typecheck")
			}
		}
	}

	return commands
}

func vcDetectPackageManager(root string) string {
	if _, err := os.Stat(filepath.Join(root, "pnpm-lock.yaml")); err == nil {
		return "pnpm"
	}
	if _, err := os.Stat(filepath.Join(root, "yarn.lock")); err == nil {
		return "yarn"
	}
	return "npm"
}

// ---------------------------------------------------------------------------
// Verification runner
// ---------------------------------------------------------------------------

func vcRunVerify(commands []string, cwd string) []vcResult {
	results := make([]vcResult, 0, len(commands))
	for _, cmd := range commands {
		args := strings.Fields(cmd)
		if len(args) == 0 {
			continue
		}
		r := core.RunCmd(args, "", vcCmdTimeout, cwd)
		passed := r != nil && r.ExitCode == 0
		output := ""
		if r != nil && !passed {
			output = r.Stdout + r.Stderr
			if len(output) > 1500 {
				output = output[:1500] + "\n... (truncated)"
			}
		}
		results = append(results, vcResult{cmd: cmd, passed: passed, output: output})
	}
	return results
}

// ---------------------------------------------------------------------------
// State management
// ---------------------------------------------------------------------------

func vcStatePath(sessionID, agentID string) string {
	key := sessionID + ":" + agentID
	h := sha256.Sum256([]byte(key))
	return filepath.Join(os.TempDir(), fmt.Sprintf(".verify-state-%x.json", h[:6]))
}

func vcLoadState(path string) map[string]any {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var state map[string]any
	if err := json.Unmarshal(data, &state); err != nil {
		return nil
	}
	return state
}

func vcSaveState(path string, state map[string]any) {
	b, err := json.Marshal(state)
	if err != nil {
		return
	}
	_ = os.WriteFile(path, b, 0o644)
}

func vcCleanupState(path string) {
	_ = os.Remove(path)
}

// asFloat64 coerces a JSON-ish numeric value to float64. Handles float64
// (JSON default), int, int64, and returns 0 for anything else.
func asFloat64(v any) float64 {
	switch n := v.(type) {
	case float64:
		return n
	case int:
		return float64(n)
	case int64:
		return float64(n)
	case float32:
		return float64(n)
	}
	return 0
}
