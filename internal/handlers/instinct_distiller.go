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
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/joneshong/hook-observatory/internal/core"
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

	if sessionID == "" {
		sessionID = "unknown"
	}

	// In-process background worker (replaces Python self-spawn).
	go idDistillWorker(transcriptPath, sessionID)
	return core.Allow()
}

// ---------------------------------------------------------------------------
// Background worker — Go port of instinct_distiller.py _main()
// ---------------------------------------------------------------------------

type idFrictionSignal struct {
	SignalType string
	SkillName  string
	Summary    string
	LineHint   int
}

var idFrictionPatterns = []struct {
	re      *regexp.Regexp
	sigType string
}{
	{regexp.MustCompile(`(?i)(retrying|retry|let me try again)`), "retry"},
	{regexp.MustCompile(`(?i)(that (didn.t|did not) work|failed|error)`), "failure"},
	{regexp.MustCompile(`不[，,]|不對|錯了|不是這樣|重來`), "correction"},
	{regexp.MustCompile(`(?i)(fallback|workaround|alternative approach)`), "fallback"},
	{regexp.MustCompile(`(?i)(no not that|don.t do that|stop|別這樣做)`), "correction"},
}

var idSkillSlashPattern = regexp.MustCompile(`/([a-z][a-z0-9-]+)`)

func idDistillWorker(transcriptPath, sessionID string) {
	signals := idExtractFrictionSignals(transcriptPath)
	idLog(fmt.Sprintf("session=%s signals=%d transcript=%s", sessionID, len(signals), transcriptPath))
	if len(signals) == 0 {
		return
	}
	idDedupAndAppend(signals, sessionID)
}

// idLog appends to ~/Claude/instinct-staging/distill.log, matching the
// Python LOG_FILE observability hook so the worker leaves a trail.
func idLog(msg string) {
	logFile := filepath.Join(idStagingDir(), "distill.log")
	if err := os.MkdirAll(filepath.Dir(logFile), 0o755); err != nil {
		return
	}
	f, err := os.OpenFile(logFile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	defer f.Close()
	ts := time.Now().Format("2006-01-02 15:04:05")
	_, _ = f.WriteString(fmt.Sprintf("[instinct_distiller] %s %s\n", ts, msg))
}

func idExtractFrictionSignals(path string) []idFrictionSignal {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var signals []idFrictionSignal
	for _, line := range strings.Split(string(raw), "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		var entry map[string]any
		if err := json.Unmarshal([]byte(line), &entry); err != nil {
			continue
		}

		msgType, _ := entry["type"].(string)
		content := ""

		switch msgType {
		case "human":
			content = idExtractText(entry)
		case "assistant":
			// Check tool_result blocks with is_error
			if blocks, ok := entry["content"].([]any); ok {
				for _, b := range blocks {
					block, ok := b.(map[string]any)
					if !ok {
						continue
					}
					if t, _ := block["type"].(string); t == "tool_result" {
						if isErr, _ := block["is_error"].(bool); isErr {
							if c, ok := block["content"].(string); ok {
								content += c + " "
							}
						}
					}
				}
			}
		}

		if content == "" {
			continue
		}

		for _, fp := range idFrictionPatterns {
			if fp.re.MatchString(content) {
				skillName := idGuessSkill(entry, content)
				summary := content
				if len(summary) > 200 {
					summary = summary[:200]
				}
				summary = strings.TrimSpace(summary)
				idx := 0
				if i, ok := entry["index"].(float64); ok {
					idx = int(i)
				}
				signals = append(signals, idFrictionSignal{
					SignalType: fp.sigType,
					SkillName:  skillName,
					Summary:    summary,
					LineHint:   idx,
				})
			}
		}
	}
	return signals
}

func idExtractText(entry map[string]any) string {
	c := entry["content"]
	if s, ok := c.(string); ok {
		return s
	}
	if blocks, ok := c.([]any); ok {
		var parts []string
		for _, b := range blocks {
			block, ok := b.(map[string]any)
			if !ok {
				continue
			}
			if t, _ := block["type"].(string); t == "text" {
				if txt, ok := block["text"].(string); ok {
					parts = append(parts, txt)
				}
			}
		}
		return strings.Join(parts, " ")
	}
	return ""
}

func idGuessSkill(entry map[string]any, content string) string {
	if m := idSkillSlashPattern.FindStringSubmatch(content); m != nil {
		return m[1]
	}
	// Look for Skill tool_use in content blocks
	if blocks, ok := entry["content"].([]any); ok {
		for _, b := range blocks {
			block, ok := b.(map[string]any)
			if !ok {
				continue
			}
			if t, _ := block["type"].(string); t == "tool_use" {
				if name, _ := block["name"].(string); name == "Skill" {
					if input, ok := block["input"].(map[string]any); ok {
						if skill, _ := input["skill"].(string); skill != "" {
							return skill
						}
					}
				}
			}
		}
	}
	return "general"
}

func idSummaryHash(skillName, sigType, summary string) string {
	key := fmt.Sprintf("%s:%s:%s", skillName, sigType, summary)
	if len(key) > 0 {
		// Mirror Python: summary truncated to 80 in hash key
		if len(summary) > 80 {
			key = fmt.Sprintf("%s:%s:%s", skillName, sigType, summary[:80])
		}
	}
	sum := sha256.Sum256([]byte(key))
	return hex.EncodeToString(sum[:])[:12]
}

func idDedupAndAppend(signals []idFrictionSignal, sessionID string) {
	stagingFile := filepath.Join(idStagingDir(), "pending.jsonl")
	existing := map[string]map[string]any{}

	if raw, err := os.ReadFile(stagingFile); err == nil {
		for _, line := range strings.Split(string(raw), "\n") {
			line = strings.TrimSpace(line)
			if line == "" {
				continue
			}
			var entry map[string]any
			if err := json.Unmarshal([]byte(line), &entry); err != nil {
				continue
			}
			if h, _ := entry["hash"].(string); h != "" {
				existing[h] = entry
			}
		}
	}

	now := time.Now().UTC().Format(time.RFC3339)

	for _, sig := range signals {
		h := idSummaryHash(sig.SkillName, sig.SignalType, sig.Summary)
		if cur, ok := existing[h]; ok {
			occ := 1
			if o, ok := cur["occurrences"].(float64); ok {
				occ = int(o)
			}
			cur["occurrences"] = occ + 1
			cur["last_seen"] = now
			existing[h] = cur
			continue
		}
		existing[h] = map[string]any{
			"hash":        h,
			"skill_name":  sig.SkillName,
			"signal_type": sig.SignalType,
			"summary":     sig.Summary,
			"evidence":    []string{"session:" + sessionID},
			"occurrences": 1,
			"reviewed":    false,
			"ts":          now,
			"last_seen":   now,
		}
	}

	// Collect all + sort by last_seen descending, unreviewed first
	all := make([]map[string]any, 0, len(existing))
	for _, e := range existing {
		all = append(all, e)
	}
	sort.SliceStable(all, func(i, j int) bool {
		li, _ := all[i]["last_seen"].(string)
		lj, _ := all[j]["last_seen"].(string)
		return li > lj
	})
	unrev := make([]map[string]any, 0, len(all))
	rev := make([]map[string]any, 0)
	for _, e := range all {
		if r, _ := e["reviewed"].(bool); r {
			rev = append(rev, e)
		} else {
			unrev = append(unrev, e)
		}
	}
	final := append(unrev, rev...)
	if len(final) > idMaxEntries {
		final = final[:idMaxEntries]
	}

	if err := os.MkdirAll(idStagingDir(), 0o755); err != nil {
		return
	}
	f, err := os.OpenFile(stagingFile, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0o644)
	if err != nil {
		return
	}
	defer f.Close()
	for _, e := range final {
		if b, err := json.Marshal(e); err == nil {
			f.Write(b)
			f.Write([]byte("\n"))
		}
	}
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
