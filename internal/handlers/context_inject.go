// Package handlers — context_inject.go
// SubagentStart handler.
// Reads .context/*.jsonl manifest files and injects context into the sub-agent.
// Resolution order:
//  1. .context/{agent_type}.jsonl (agent-specific override)
//  2. .context/default.jsonl (project-wide override)
//  3. Auto-detect from project structure (zero-config)
package handlers

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/joneshong/hook-observatory/internal/core"
)

const contextInjectMaxSize = 8000

func init() {
	core.Register("SubagentStart", core.Entry{
		Matcher:    "",
		Handler:    contextInjectHandle,
		Critical:   false,
		ModuleName: "context_inject",
	})
}

func contextInjectHandle(eventType, _ string, _ map[string]any, rawInput string) core.HookResult {
	if eventType != "SubagentStart" {
		return core.Allow()
	}

	var data map[string]any
	if strings.TrimSpace(rawInput) != "" {
		if err := json.Unmarshal([]byte(rawInput), &data); err != nil {
			return core.Allow()
		}
	}
	if data == nil {
		data = map[string]any{}
	}

	agentType, _ := data["agent_type"].(string)
	if agentType == "" {
		agentType, _ = data["subagent_type"].(string)
	}
	if agentType == "" {
		return core.Allow()
	}

	cwd, _ := data["cwd"].(string)
	if cwd == "" {
		cwd, _ = os.Getwd()
	}

	root := contextInjectFindProjectRoot(cwd)

	// Priority 1: .context/ JSONL files
	contextDir := contextInjectFindContextDir(cwd)
	var entries []map[string]any
	source := ""

	if contextDir != "" {
		for _, candidate := range []string{
			filepath.Join(contextDir, agentType+".jsonl"),
			filepath.Join(contextDir, "default.jsonl"),
		} {
			entries = contextInjectReadJSONL(candidate)
			if len(entries) > 0 {
				source = ".context/"
				break
			}
		}
	}

	// Priority 2: auto-detect
	if len(entries) == 0 {
		entries = contextInjectAutoDetect(root)
		if len(entries) > 0 {
			source = "auto-detect"
		}
	}

	if len(entries) == 0 {
		return core.Allow()
	}

	contextText := contextInjectBuildContext(entries, root)
	if contextText == "" {
		return core.Allow()
	}

	header := fmt.Sprintf("[context-inject] Loaded from %s for %s:", source, agentType)
	return core.Message(header + "\n\n" + contextText)
}

func contextInjectFindContextDir(cwd string) string {
	candidate := filepath.Join(cwd, ".context")
	if info, err := os.Stat(candidate); err == nil && info.IsDir() {
		return candidate
	}
	result := core.RunCmd([]string{"git", "rev-parse", "--show-toplevel"}, "", 5*time.Second, cwd)
	if result != nil && result.ExitCode == 0 {
		gitRoot := strings.TrimSpace(result.Stdout)
		if gitRoot != cwd {
			candidate = filepath.Join(gitRoot, ".context")
			if info, err := os.Stat(candidate); err == nil && info.IsDir() {
				return candidate
			}
		}
	}
	return ""
}

func contextInjectReadJSONL(path string) []map[string]any {
	f, err := os.Open(path)
	if err != nil {
		return nil
	}
	defer f.Close()

	var entries []map[string]any
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		var entry map[string]any
		if err := json.Unmarshal([]byte(line), &entry); err != nil {
			continue
		}
		entries = append(entries, entry)
	}
	return entries
}

func contextInjectReadFile(path, baseDir string) string {
	fullPath := path
	if !filepath.IsAbs(path) {
		fullPath = filepath.Join(baseDir, path)
	}
	data, err := os.ReadFile(fullPath)
	if err != nil {
		return ""
	}
	return string(data)
}

func contextInjectReadDirectoryMD(path, baseDir string) string {
	fullPath := path
	if !filepath.IsAbs(path) {
		fullPath = filepath.Join(baseDir, path)
	}
	entries, err := os.ReadDir(fullPath)
	if err != nil {
		return ""
	}
	var names []string
	for _, e := range entries {
		if strings.HasSuffix(e.Name(), ".md") {
			names = append(names, e.Name())
		}
	}
	sort.Strings(names)

	var parts []string
	for _, name := range names {
		data, err := os.ReadFile(filepath.Join(fullPath, name))
		if err != nil {
			continue
		}
		parts = append(parts, fmt.Sprintf("### %s\n%s", name, string(data)))
	}
	return strings.Join(parts, "\n\n")
}

func contextInjectBuildContext(entries []map[string]any, baseDir string) string {
	var sections []string
	totalSize := 0

	for _, entry := range entries {
		filePath, _ := entry["file"].(string)
		reason, _ := entry["reason"].(string)
		entryType, _ := entry["type"].(string)
		if entryType == "" {
			entryType = "file"
		}

		if filePath == "" {
			continue
		}

		var content string
		if entryType == "directory" {
			content = contextInjectReadDirectoryMD(filePath, baseDir)
		} else {
			content = contextInjectReadFile(filePath, baseDir)
		}

		if content == "" {
			continue
		}

		label := reason
		if label == "" {
			label = filePath
		}
		section := fmt.Sprintf("## %s\n%s", label, content)

		if totalSize+len(section) > contextInjectMaxSize {
			sections = append(sections, fmt.Sprintf("... (context truncated at %d chars)", contextInjectMaxSize))
			break
		}
		sections = append(sections, section)
		totalSize += len(section)
	}

	return strings.Join(sections, "\n\n")
}

func contextInjectFindProjectRoot(cwd string) string {
	result := core.RunCmd([]string{"git", "rev-parse", "--show-toplevel"}, "", 5*time.Second, cwd)
	if result != nil && result.ExitCode == 0 {
		root := strings.TrimSpace(result.Stdout)
		if root != "" {
			return root
		}
	}
	return cwd
}

func contextInjectAutoDetect(root string) []map[string]any {
	var entries []map[string]any
	home, _ := os.UserHomeDir()

	// Project-level CLAUDE.md (skip ~/.claude/CLAUDE.md)
	claudeMD := filepath.Join(root, "CLAUDE.md")
	homeClaude := filepath.Join(home, ".claude", "CLAUDE.md")
	if _, err := os.Stat(claudeMD); err == nil {
		realClaude, _ := filepath.EvalSymlinks(claudeMD)
		realHome, _ := filepath.EvalSymlinks(homeClaude)
		if realClaude != realHome {
			entries = append(entries, map[string]any{
				"file":   "CLAUDE.md",
				"reason": "Project instructions",
			})
		}
	}

	// spec/ or docs/ directories
	for _, pair := range [][2]string{{"spec", "Specifications"}, {"docs", "Documentation"}} {
		dirName, reason := pair[0], pair[1]
		dirPath := filepath.Join(root, dirName)
		if info, err := os.Stat(dirPath); err == nil && info.IsDir() {
			if contextInjectHasMD(dirPath) {
				entries = append(entries, map[string]any{
					"file":   dirName,
					"reason": reason,
					"type":   "directory",
				})
			}
		}
	}

	// .claude/rules/ (project-specific, not global ~/.claude/rules/)
	rulesDir := filepath.Join(root, ".claude", "rules")
	if info, err := os.Stat(rulesDir); err == nil && info.IsDir() {
		if contextInjectHasMD(rulesDir) {
			entries = append(entries, map[string]any{
				"file":   ".claude/rules",
				"reason": "Project rules",
				"type":   "directory",
			})
		}
	}

	return entries
}

func contextInjectHasMD(dir string) bool {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return false
	}
	for _, e := range entries {
		if strings.HasSuffix(e.Name(), ".md") {
			return true
		}
	}
	return false
}
