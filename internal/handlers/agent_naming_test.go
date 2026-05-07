package handlers

import (
	"strings"
	"testing"
)

func TestAgentNamingNonAgentTool(t *testing.T) {
	// Edge: non-Agent tool → always allow
	res := agentNamingHandle("PreToolUse", "Bash",
		map[string]any{"description": "", "prompt": "do something"},
		"",
	)
	if res.IsBlock() {
		t.Errorf("non-Agent tool should allow, got block: %q", res.Reason)
	}
}

func TestAgentNamingMissingDescriptionBlocks(t *testing.T) {
	// Error path: schema requires description; reject if missing
	res := agentNamingHandle("PreToolUse", "Agent",
		map[string]any{"prompt": "implement the feature"},
		"",
	)
	if !res.IsBlock() {
		t.Errorf("missing description should block, got decision=%q", res.Decision)
	}
	if !strings.Contains(res.Reason, "description") {
		t.Errorf("block reason should mention 'description', got %q", res.Reason)
	}
}

func TestAgentNamingEmptyDescriptionBlocks(t *testing.T) {
	// Error path: empty/whitespace description → block
	res := agentNamingHandle("PreToolUse", "Agent",
		map[string]any{"description": "   ", "prompt": "implement the feature"},
		"",
	)
	if !res.IsBlock() {
		t.Errorf("empty description should block, got decision=%q", res.Decision)
	}
}

func TestAgentNamingSpecializedTypeAllows(t *testing.T) {
	// Rule 2: specialized subagent_type → allow silently
	res := agentNamingHandle("PreToolUse", "Agent",
		map[string]any{
			"description":   "scan auth routes",
			"subagent_type": "explorer",
			"prompt":        "explore codebase",
		},
		"",
	)
	if res.IsBlock() || res.Message != "" {
		t.Errorf("specialized type should allow silently, got %+v", res)
	}
}

func TestAgentNamingMCPKeywordAllows(t *testing.T) {
	// Rule 3: MCP keywords → allow silently even as general-purpose
	res := agentNamingHandle("PreToolUse", "Agent",
		map[string]any{
			"description":   "MCP task",
			"subagent_type": "general-purpose",
			"prompt":        "use mcpproxy to retrieve_tools and call_tool",
		},
		"",
	)
	if res.IsBlock() || res.Message != "" {
		t.Errorf("MCP-dependent task should allow silently, got %+v", res)
	}
}

func TestAgentNamingKeywordSuggestsType(t *testing.T) {
	// Rule 4: keyword match → message with suggestion
	res := agentNamingHandle("PreToolUse", "Agent",
		map[string]any{
			"description": "do stuff",
			"prompt":      "implement the authentication feature",
		},
		"",
	)
	if res.IsBlock() {
		t.Errorf("should not block on suggestion, got block: %q", res.Reason)
	}
	if res.Message == "" {
		t.Error("expected suggestion message, got empty")
	}
	if !strings.Contains(res.Message, "worker") {
		t.Errorf("expected 'worker' in suggestion for 'implement', got %q", res.Message)
	}
}

func TestAgentNamingNoKeywordAllows(t *testing.T) {
	// Happy path: description present, no special keyword → allow with no message
	res := agentNamingHandle("PreToolUse", "Agent",
		map[string]any{
			"description": "my task",
			"prompt":      "do something unusual",
		},
		"",
	)
	if res.IsBlock() {
		t.Errorf("unknown prompt should allow, got block: %q", res.Reason)
	}
}

func TestAgentNamingSuggestBrowser(t *testing.T) {
	res := agentNamingHandle("PreToolUse", "Agent",
		map[string]any{
			"description": "scrape site",
			"prompt":      "use playwright to scrape the website",
		},
		"",
	)
	if res.Message == "" {
		t.Error("expected browser suggestion for playwright keyword")
	}
	if !strings.Contains(res.Message, "browser") {
		t.Errorf("expected 'browser' in suggestion, got %q", res.Message)
	}
}

// Regression: schema declares additionalProperties:false, so any `name`
// field is filtered out before the hook runs. Even if a `name` somehow
// arrives, it must not affect the decision — only `description` matters.
func TestAgentNamingIgnoresNameField(t *testing.T) {
	res := agentNamingHandle("PreToolUse", "Agent",
		map[string]any{
			"name":        "legacy-name",
			"description": "regression check",
			"prompt":      "do something unusual",
		},
		"",
	)
	if res.IsBlock() {
		t.Errorf("presence of legacy `name` should not affect decision, got block: %q", res.Reason)
	}
}
