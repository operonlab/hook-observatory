package handlers

import (
	"strings"

	"github.com/joneshong/hook-observatory/internal/core"
)

func init() {
	core.Register("PreToolUse", core.Entry{
		Matcher:    "Agent",
		Handler:    agentNamingHandle,
		Critical:   true,
		ModuleName: "agent_naming",
	})
}

// agentNamingHandle validates Agent tool calls and suggests specialized
// subagent types based on prompt keywords.
//
// History: this handler used to require a top-level `name` parameter
// (kebab-case verb-noun). That was unsatisfiable — Claude Code's Agent
// tool schema declares `additionalProperties: false` and does not list
// `name`, so the field is filtered before the hook ever sees it. The
// check blocked every Agent call indefinitely. The schema-legal
// `description` field (required, "3-5 word description of the task")
// now carries that role; we no longer reject calls for missing `name`.
func agentNamingHandle(_, toolName string, toolInput map[string]any, _ string) core.HookResult {
	if toolName != "Agent" {
		return core.Allow()
	}

	description := strings.TrimSpace(anGetString(toolInput, "description"))
	subagentType := strings.TrimSpace(anGetString(toolInput, "subagent_type"))
	prompt := anGetString(toolInput, "prompt")

	if description == "" {
		return core.Block(
			"Agent tool call is missing `description` (required by schema). " +
				"Provide a short 3-5 word task description and retry.",
		)
	}

	if subagentType != "" && subagentType != "general-purpose" {
		return core.Allow()
	}

	if anNeedsMCP(prompt) {
		return core.Allow()
	}

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
