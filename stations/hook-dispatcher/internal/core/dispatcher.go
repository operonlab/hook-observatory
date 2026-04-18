package core

import (
	"encoding/json"
	"fmt"
	"strings"
	"sync"
	"time"
)

// Handler is the function signature every hook handler implements.
// Mirrors the Python signature in handlers/__init__.py.
type Handler func(eventType, toolName string, toolInput map[string]any, rawInput string) HookResult

// Entry is a registry entry: a (matcher, handler) pair + criticality flag.
//
// Matcher semantics:
//
//	""      → always run (catch-all)
//	"A|B|C" → run only when toolName ∈ {A, B, C}
//
// Critical handlers always run regardless of the 5s budget.
// ModuleName is used for config-driven enable/disable lookups.
type Entry struct {
	Matcher    string
	Handler    Handler
	Critical   bool
	ModuleName string
}

var (
	regMu    sync.Mutex
	registry = map[string][]Entry{}
)

// Register adds a handler entry to the registry.
// Called from handler init() functions.
func Register(eventType string, entry Entry) {
	regMu.Lock()
	defer regMu.Unlock()
	registry[eventType] = append(registry[eventType], entry)
}

// Reset wipes the registry. Tests use it to start from a known state.
func Reset() {
	regMu.Lock()
	defer regMu.Unlock()
	registry = map[string][]Entry{}
}

func matches(matcher, toolName string) bool {
	if matcher == "" {
		return true
	}
	for _, part := range strings.Split(matcher, "|") {
		if part == toolName {
			return true
		}
	}
	return false
}

// parseInput extracts tool_name + tool_input from a hook payload.
// Returns zero values on malformed JSON (fail-open).
func parseInput(raw string) (toolName string, toolInput map[string]any) {
	toolInput = map[string]any{}
	trimmed := strings.TrimSpace(raw)
	if trimmed == "" {
		return
	}
	var parsed map[string]any
	if err := json.Unmarshal([]byte(trimmed), &parsed); err != nil {
		return
	}
	if v, ok := parsed["tool_name"].(string); ok {
		toolName = v
	}
	if v, ok := parsed["tool_input"].(map[string]any); ok {
		toolInput = v
	}
	return
}

// safeCall invokes a handler with panic recovery (fail-open).
func safeCall(h Handler, eventType, toolName string, toolInput map[string]any, rawInput string) (res HookResult) {
	defer func() {
		if r := recover(); r != nil {
			res = Allow()
		}
	}()
	return h(eventType, toolName, toolInput, rawInput)
}

// Dispatch is the main entry point. Routes to matching handlers, merges results,
// returns the final output (JSON string or passthrough text).
//
// Mirrors handlers/__init__.py dispatch() byte-for-byte on output format.
func Dispatch(eventType, rawInput string) string {
	toolName, toolInput := parseInput(rawInput)

	entries := enabledEntries(eventType)
	criticals, deferrables := splitByCriticality(entries)

	acc := &accumulator{}
	start := time.Now()
	budget := time.Duration(Cfg().GetBudgetMs()) * time.Millisecond

	// Phase 1 — critical handlers, no budget
	for _, e := range criticals {
		if !matches(e.Matcher, toolName) {
			continue
		}
		acc.merge(safeCall(e.Handler, eventType, toolName, toolInput, rawInput))
	}

	// Phase 2 — deferrable handlers, 5s budget
	skipped := 0
	for _, e := range deferrables {
		if !matches(e.Matcher, toolName) {
			continue
		}
		if time.Since(start) > budget {
			skipped++
			continue
		}
		acc.merge(safeCall(e.Handler, eventType, toolName, toolInput, rawInput))
	}
	if skipped > 0 {
		acc.Messages = append(acc.Messages, fmt.Sprintf("⏱️ %d handler(s) skipped (budget exceeded)", skipped))
	}

	return buildOutput(eventType, acc)
}

func enabledEntries(eventType string) []Entry {
	regMu.Lock()
	defer regMu.Unlock()
	raw := registry[eventType]
	out := make([]Entry, 0, len(raw))
	cfg := Cfg()
	for _, e := range raw {
		if e.ModuleName != "" && !cfg.IsHandlerEnabled(e.ModuleName) {
			continue
		}
		out = append(out, e)
	}
	return out
}

func splitByCriticality(entries []Entry) (criticals, deferrables []Entry) {
	for _, e := range entries {
		if e.Critical {
			criticals = append(criticals, e)
		} else {
			deferrables = append(deferrables, e)
		}
	}
	return
}

// buildOutput converts the accumulator into the final string output.
// Byte-identical to Python dispatch() output format.
func buildOutput(eventType string, a *accumulator) string {
	// UserPromptSubmit with passthrough parts → raw text join
	if eventType == "UserPromptSubmit" && len(a.PassthroughParts) > 0 {
		return strings.Join(a.PassthroughParts, "\n")
	}

	// Block decision wins — no rewrite
	if a.Decision == "block" {
		out := map[string]any{"decision": "block"}
		if a.Reason != "" {
			out["reason"] = a.Reason
		}
		if len(a.Messages) > 0 {
			out["message"] = strings.Join(a.Messages, "; ")
		}
		return mustMarshal(out)
	}

	// Rewrite path
	if a.UpdatedInput != nil {
		return mustMarshal(map[string]any{
			"hookSpecificOutput": map[string]any{
				"hookEventName":            "PreToolUse",
				"permissionDecision":       "allow",
				"permissionDecisionReason": "RTK auto-rewrite",
				"updatedInput":             a.UpdatedInput,
			},
		})
	}

	// Normal case
	out := map[string]any{}
	if a.Decision != "" {
		out["decision"] = a.Decision
	}
	if len(a.Messages) > 0 {
		out["message"] = strings.Join(a.Messages, "; ")
	}
	return mustMarshal(out)
}

func mustMarshal(v any) string {
	b, err := json.Marshal(v)
	if err != nil {
		return "{}"
	}
	return string(b)
}
