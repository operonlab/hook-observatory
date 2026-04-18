package handlers

import (
	"strings"

	"github.com/joneshong/hook-dispatcher/internal/core"
)

func init() {
	core.Register("PreToolUse", core.Entry{
		Matcher:    "Agent",
		Handler:    agentNamingHandle,
		Critical:   true,
		ModuleName: "agent_naming",
	})
}

// agentNamingHandle is the Go port of handlers/agent_naming.py.
//
// Enforces that every Agent tool call has a descriptive `name` parameter
// (kebab-case verb-noun). Suggests a specialized subagent_type when keyword
// matching finds a better fit than general-purpose.
func agentNamingHandle(_, toolName string, toolInput map[string]any, _ string) core.HookResult {
	if toolName != "Agent" {
		return core.Allow()
	}

	name := strings.TrimSpace(anGetString(toolInput, "name"))
	subagentType := strings.TrimSpace(anGetString(toolInput, "subagent_type"))
	prompt := anGetString(toolInput, "prompt")

	// Rule 1: name is mandatory
	if name == "" {
		return core.Block(
			`Agent must have a ` + "`name`" + ` parameter (kebab-case verb-noun, ` +
				`e.g. name: "scan-auth-routes"). Add a descriptive name and retry.`,
		)
	}

	// Rule 2: if using a specialized type (not general-purpose / empty), allow silently
	if subagentType != "" && subagentType != "general-purpose" {
		return core.Allow()
	}

	// Rule 3: general-purpose with MCP need → allow silently
	if anNeedsMCP(prompt) {
		return core.Allow()
	}

	// Rule 4: suggest a better type if keyword matches
	if suggested := anSuggestType(prompt); suggested != "" {
		return core.Message(
			"💡 Consider using `subagent_type: \"" + suggested + "\"` for this task " +
				"(matched keywords in prompt). general-purpose also works but " +
				"specialized agents have focused tools and cost less.",
		)
	}

	return core.Allow()
}

// ---------------------------------------------------------------------------
// Keyword mapping — ordered by specificity, first match wins.
// Mirrors Python KEYWORD_MAP exactly.
// ---------------------------------------------------------------------------

type anKeywordEntry struct {
	agentType string
	keywords  []string
}

var anKeywordMap = []anKeywordEntry{
	// Dispatchers
	{"codex-dispatcher", []string{"codex", "gpt-"}},
	{"gemini-dispatcher", []string{"gemini"}},
	{"copilot-dispatcher", []string{"copilot"}},
	// Specific agents
	{"chaos-engineer", []string{"chaos", "fault inject", "resilience test"}},
	{"media", []string{"video", "audio", "image process", "screen record", "ocr", "transcri", "tts", "stt"}},
	{"browser", []string{"browser", "playwright", "scrape", "web page", "notebookllm"}},
	{"designer", []string{"diagram", "mermaid", "theme", "visual design", "ui design", "frontend design"}},
	// General agents
	{"researcher", []string{"research", "search web", "look up", "competitive", "company intel"}},
	{"reviewer", []string{"review", "audit", "quality check", "verify code", "security scan"}},
	{"writer", []string{"write doc", "draft doc", "content gen", "readme", "changelog", "spec"}},
	{"worker", []string{"implement", "edit file", "fix bug", "build", "scaffold", "refactor", "create file"}},
	{"explorer", []string{"explore", "scan code", "find file", "codebase", "catalog", "topology"}},
}

var anMCPKeywords = []string{"mcpproxy", "retrieve_tools", "call_tool", "mcp server", "mcp tool"}

func anSuggestType(prompt string) string {
	lower := strings.ToLower(prompt)
	for _, entry := range anKeywordMap {
		for _, kw := range entry.keywords {
			if strings.Contains(lower, kw) {
				return entry.agentType
			}
		}
	}
	return ""
}

func anNeedsMCP(prompt string) bool {
	lower := strings.ToLower(prompt)
	for _, kw := range anMCPKeywords {
		if strings.Contains(lower, kw) {
			return true
		}
	}
	return false
}

func anGetString(m map[string]any, key string) string {
	v, _ := m[key].(string)
	return v
}
