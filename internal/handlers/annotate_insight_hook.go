package handlers

// annotate_insight_hook.go — Go port of handlers/annotate_insight_hook.py
//
// PostToolUse / mcp__memvault__annotate_insight:
//   Fires a background goroutine that calls LiteLLM to suggest additional
//   tags for the annotated insight, then PATCHes the memvault block.
//
// Design:
//   - Fire-and-forget: all enrichment runs in a goroutine, handler returns Allow() immediately.
//   - Fail-safe: any error silently degrades, main flow is unaffected.

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"

	"github.com/joneshong/hook-observatory/internal/clients"
	"github.com/joneshong/hook-observatory/internal/core"
)

const (
	annotateToolPattern = "mcp__memvault__annotate_insight"
	annotateTagModel    = "qwen3.5-flash"
	annotateMaxTokens   = 60
	annotateTemp        = 0.3
)

// NOTE: Not registered. Python handlers/__init__.py does not import or register
// annotate_insight_hook — it's inactive in production. Keeping the
// implementation for future opt-in, but no core.Register() call to preserve
// parity.
func init() {}

func annotateInsightHandle(_, toolName string, toolInput map[string]any, rawInput string) core.HookResult {
	if toolName != annotateToolPattern {
		return core.Allow()
	}

	// Parse raw input to get tool_response + tool_input fields
	var data map[string]any
	if err := json.Unmarshal([]byte(rawInput), &data); err != nil {
		return core.Allow()
	}

	toolResponse, _ := data["tool_response"].(string)

	// Resolve tool_input: prefer root-level tool_input from JSON, fallback to passed map
	resolvedInput, _ := data["tool_input"].(map[string]any)
	if resolvedInput == nil {
		resolvedInput = toolInput
	}

	insight, _ := resolvedInput["insight"].(string)

	// Collect existing tags
	var existingTags []string
	if tagsRaw, ok := resolvedInput["tags"]; ok {
		switch v := tagsRaw.(type) {
		case []interface{}:
			for _, t := range v {
				if s, ok := t.(string); ok {
					existingTags = append(existingTags, s)
				}
			}
		case []string:
			existingTags = v
		}
	}
	existingTags = append(existingTags, "realtime-annotation")

	// Parse Block ID from tool_response (format: "Block ID: <uuid>")
	blockID := ""
	for _, line := range strings.Split(toolResponse, "\n") {
		if strings.HasPrefix(line, "Block ID:") {
			blockID = strings.TrimSpace(strings.SplitN(line, ":", 2)[1])
			break
		}
	}

	if blockID == "" || insight == "" {
		return core.Allow()
	}

	// Fire-and-forget: enrich tags in background goroutine
	go annotateEnrichBackground(blockID, insight, existingTags)

	return core.Allow()
}

// annotateEnrichBackground calls LiteLLM, merges tags, PATCHes memvault block.
// Runs in a goroutine — all errors are silent.
func annotateEnrichBackground(blockID, insight string, existingTags []string) {
	newTags := annotateSuggestTags(insight, existingTags)
	if len(newTags) == 0 {
		return
	}

	// Merge + deduplicate
	seen := make(map[string]struct{}, len(existingTags)+len(newTags))
	merged := make([]string, 0, len(existingTags)+len(newTags))
	for _, t := range existingTags {
		if _, ok := seen[t]; !ok {
			seen[t] = struct{}{}
			merged = append(merged, t)
		}
	}
	for _, t := range newTags {
		if _, ok := seen[t]; !ok {
			seen[t] = struct{}{}
			merged = append(merged, t)
		}
	}

	mc := clients.NewMemvaultClient()
	_, _ = mc.UpdateBlock(blockID, map[string]any{"tags": merged})
}

// annotateSuggestTags calls LiteLLM and returns up to 3 new tag suggestions.
func annotateSuggestTags(insight string, existingTags []string) []string {
	litellmModel := os.Getenv("ANNOTATE_TAG_MODEL")
	if litellmModel == "" {
		litellmModel = annotateTagModel
	}

	existingStr := "(none)"
	if len(existingTags) > 0 {
		existingStr = strings.Join(existingTags, ", ")
	}

	truncated := insight
	if len(truncated) > 300 {
		truncated = truncated[:300]
	}

	prompt := fmt.Sprintf(
		"Given the following insight, suggest 2-3 short tag keywords "+
			"(in Traditional Chinese or English) "+
			"that would help categorize it for future retrieval. "+
			"Return ONLY a JSON array of strings, no explanation.\n\n"+
			"Existing tags: %s\n"+
			"Insight: %s",
		existingStr, truncated,
	)

	content, err := clients.LiteLLMComplete(
		litellmModel,
		[]clients.LiteLLMMessage{{Role: "user", Content: prompt}},
		annotateMaxTokens,
		annotateTemp,
	)
	if err != nil {
		return nil
	}

	raw := strings.TrimSpace(content)
	if !strings.HasPrefix(raw, "[") {
		return nil
	}

	var suggested []interface{}
	if err := json.Unmarshal([]byte(raw), &suggested); err != nil {
		return nil
	}

	// Filter existing, take max 3
	existingSet := make(map[string]struct{}, len(existingTags))
	for _, t := range existingTags {
		existingSet[t] = struct{}{}
	}

	var result []string
	for _, item := range suggested {
		s, ok := item.(string)
		if !ok {
			continue
		}
		s = strings.TrimSpace(s)
		if s == "" {
			continue
		}
		if _, exists := existingSet[s]; !exists {
			result = append(result, s)
		}
		if len(result) >= 3 {
			break
		}
	}
	return result
}
