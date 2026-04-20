package handlers

// instinct_distiller.go — Go port of handlers/instinct_distiller.py
//
// SessionEnd: spawn background distillation worker (self-invocation in Python;
//
//	here we invoke the Python script directly since Go has no equivalent
//	of __main__ self-spawn).
//
// SessionStart: read pending.jsonl and emit a summary of unreviewed instincts.

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/joneshong/hook-dispatcher/internal/core"
)

const (
	idMaxEntries = 500
	idMaxPreview = 3
)

func init() {
	entry := core.Entry{
		Matcher:    "",
		Handler:    instinctDistillerHandle,
		Critical:   false,
		ModuleName: "instinct_distiller",
	}
	core.Register("SessionEnd", entry)
	core.Register("SessionStart", entry)
}

func instinctDistillerHandle(eventType, _ string, _ map[string]any, rawInput string) core.HookResult {
	switch eventType {
	case "SessionEnd":
		return idHandleSessionEnd(rawInput)
	case "SessionStart":
		return idHandleSessionStart()
	default:
		return core.Allow()
	}
}

// ---------------------------------------------------------------------------
// SessionEnd: spawn background distillation
// ---------------------------------------------------------------------------

func idHandleSessionEnd(rawInput string) core.HookResult {
	var data map[string]any
	if rawInput != "" {
		if err := json.Unmarshal([]byte(rawInput), &data); err != nil {
			return core.Allow()
		}
	}

	transcriptPath, _ := data["transcript_path"].(string)
	sessionID, _ := data["session_id"].(string)
	if transcriptPath == "" {
		return core.Allow()
	}
	if _, err := os.Stat(transcriptPath); err != nil {
		return core.Allow()
	}

	stagingDir := idStagingDir()
	if err := os.MkdirAll(stagingDir, 0o755); err != nil {
		return core.Allow()
	}

	// Python self-spawns using sys.executable + __file__.
	// We replicate by calling the Python handler file as __main__.
	home, _ := os.UserHomeDir()
	observatoryRoot := filepath.Join(home, "workshop", "stations", "hook-observatory")
	handlerPy := filepath.Join(observatoryRoot, "handlers", "instinct_distiller.py")
	python := core.Cfg().GetTool("python")
	if python == "" {
		python = filepath.Join(home, ".local", "bin", "python3")
	}

	if sessionID == "" {
		sessionID = "unknown"
	}

	_ = core.RunBackground([]string{python, handlerPy, transcriptPath, sessionID}, "")
	return core.Allow()
}

// ---------------------------------------------------------------------------
// SessionStart: notify pending instincts
// ---------------------------------------------------------------------------

func idHandleSessionStart() core.HookResult {
	pending := idLoadPending()
	if len(pending) == 0 {
		return core.Allow()
	}

	skillGroups := map[string]int{}
	for _, entry := range pending {
		skill, _ := entry["skill_name"].(string)
		if skill == "" {
			skill = "unknown"
		}
		skillGroups[skill]++
	}

	// Sort by count descending
	type skillCount struct {
		name  string
		count int
	}
	sorted := make([]skillCount, 0, len(skillGroups))
	for name, count := range skillGroups {
		sorted = append(sorted, skillCount{name, count})
	}
	sort.Slice(sorted, func(i, j int) bool { return sorted[i].count > sorted[j].count })

	parts := []string{
		"## Instinct 候選待審 (" + itoa(len(pending)) + " 條, " + itoa(len(skillGroups)) + " skills)",
	}

	preview := idMaxPreview
	if len(sorted) < preview {
		preview = len(sorted)
	}
	for _, sc := range sorted[:preview] {
		parts = append(parts, "- **"+sc.name+"**: "+itoa(sc.count)+" friction signal(s)")
	}
	if len(skillGroups) > idMaxPreview {
		parts = append(parts, "  ... 還有 "+itoa(len(skillGroups)-idMaxPreview)+" skills")
	}
	parts = append(parts, "使用 `/review-instincts` 審閱")

	return core.Message(strings.Join(parts, "\n"))
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func idStagingDir() string {
	dataDir := core.Cfg().GetPath("data_dir")
	if dataDir == "" {
		home, _ := os.UserHomeDir()
		dataDir = filepath.Join(home, ".claude", "data")
	}
	return filepath.Join(dataDir, "instincts")
}

func idLoadPending() []map[string]any {
	stagingFile := filepath.Join(idStagingDir(), "pending.jsonl")
	raw, err := os.ReadFile(stagingFile)
	if err != nil {
		return nil
	}

	var entries []map[string]any
	for _, line := range strings.Split(string(raw), "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		var entry map[string]any
		if err := json.Unmarshal([]byte(line), &entry); err != nil {
			continue
		}
		reviewed, _ := entry["reviewed"].(bool)
		if !reviewed {
			entries = append(entries, entry)
		}
	}
	return entries
}
