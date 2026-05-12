package handlers

// memory_sync.go — Go in-process port of handlers/memory_sync.py
//
// PostToolUse+Edit/Write: detect memory file writes and sync to memvault
// via POST /api/memvault/blocks (fire-and-forget goroutine).
//
// Parity notes:
//   - Python version fork exec'd itself with `python3 memory_sync.py <path>`
//     which imported MemvaultClient.extract() → POST /blocks.
//   - Go version does the HTTP POST in-process in a goroutine.
//   - YAML frontmatter parser mirrors the simple regex approach of the
//     Python _parse_frontmatter (no full YAML library needed).

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"github.com/joneshong/hook-dispatcher/internal/core"
	portregistry "github.com/joneshong/workshop/libs/go-port-registry"
)

func init() {
	core.Register("PostToolUse", core.Entry{
		Matcher:    "Edit|Write",
		Handler:    memorySyncHandle,
		Critical:   false,
		ModuleName: "memory_sync",
	})
}

// memorySyncCoreAPI is resolved from the cross-language port registry
// (core = 10000) at package init.
var memorySyncCoreAPI = portregistry.URL("core", "/api/memvault", 10000)

var memorySyncTypeMap = map[string]string{
	"user":      "general",
	"feedback":  "attitude",
	"project":   "knowledge",
	"reference": "knowledge",
}

var memorySyncFrontmatterPattern = regexp.MustCompile(`(?s)^---\s*\n(.*?)\n---\s*\n(.*)`)

func memorySyncHandle(_, toolName string, toolInput map[string]any, _ string) core.HookResult {
	if toolName != "Edit" && toolName != "Write" {
		return core.Allow()
	}
	filePath, _ := toolInput["file_path"].(string)
	if filePath == "" {
		return core.Allow()
	}
	if !memorySyncIsMemoryFile(filePath) {
		return core.Allow()
	}

	realPath, err := filepath.EvalSymlinks(filePath)
	if err != nil {
		realPath = filePath
	}

	go memorySyncWorker(realPath)
	fmt.Fprintf(os.Stderr, "[memory-sync] triggered sync: %s\n", filepath.Base(filePath))
	return core.Allow()
}

func memorySyncIsMemoryFile(path string) bool {
	home, _ := os.UserHomeDir()
	projectsDir := filepath.Join(home, ".claude", "projects")

	real, err := filepath.EvalSymlinks(path)
	if err != nil {
		real = path
	}
	if !strings.HasPrefix(real, projectsDir) {
		return false
	}
	if !strings.Contains(real, "/memory/") {
		return false
	}
	base := filepath.Base(real)
	return strings.HasSuffix(base, ".md") && base != "MEMORY.md"
}

// memorySyncWorker reads a memory file, parses its frontmatter, and POSTs
// a memory block to the memvault Core API. Mirrors Python _worker().
func memorySyncWorker(filePath string) {
	data, err := os.ReadFile(filePath)
	if err != nil {
		return
	}
	raw := string(data)
	if strings.TrimSpace(raw) == "" {
		return
	}

	meta, body := memorySyncParseFrontmatter(raw)

	memType := meta["type"]
	if memType == "" {
		memType = "general"
	}
	blockType := "general"
	if v, ok := memorySyncTypeMap[memType]; ok {
		blockType = v
	}

	basename := strings.TrimSuffix(filepath.Base(filePath), ".md")
	tags := []string{"auto-memory", memType, basename}

	name := meta["name"]
	if name == "" {
		name = basename
	}
	description := meta["description"]
	extractContent := body
	if description != "" {
		extractContent = fmt.Sprintf("[%s] %s\n\n%s", name, description, body)
	}

	postBody := map[string]any{
		"content":    extractContent,
		"block_type": blockType,
		"tags":       tags,
	}
	bodyBytes, err := json.Marshal(postBody)
	if err != nil {
		return
	}

	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Post(memorySyncCoreAPI+"/blocks", "application/json", bytes.NewReader(bodyBytes))
	if err != nil {
		fmt.Fprintf(os.Stderr, "[memory-sync] sync failed for %s: %v\n", basename, err)
		return
	}
	defer resp.Body.Close()
	fmt.Fprintf(os.Stderr, "[memory-sync] synced %s → memvault (status=%d)\n", basename, resp.StatusCode)
}

// memorySyncParseFrontmatter parses simple YAML-ish frontmatter (key: value
// pairs between `---` markers). Mirrors the Python _parse_frontmatter behaviour.
func memorySyncParseFrontmatter(content string) (map[string]string, string) {
	m := memorySyncFrontmatterPattern.FindStringSubmatch(content)
	if m == nil {
		return map[string]string{}, strings.TrimSpace(content)
	}
	meta := map[string]string{}
	for _, line := range strings.Split(m[1], "\n") {
		idx := strings.Index(line, ":")
		if idx <= 0 {
			continue
		}
		key := strings.TrimSpace(line[:idx])
		val := strings.TrimSpace(line[idx+1:])
		val = strings.Trim(val, `"'`)
		meta[key] = val
	}
	return meta, strings.TrimSpace(m[2])
}

// memorySyncParseRawInput is a helper used by tests.
func memorySyncParseRawInput(raw string) map[string]any {
	var out map[string]any
	_ = json.Unmarshal([]byte(raw), &out)
	return out
}
