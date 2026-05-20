package core

import (
	"strings"
	"testing"
)

func TestDispatchEmptyRegistry(t *testing.T) {
	Reset()
	out := Dispatch("PreToolUse", `{"tool_name":"Bash","tool_input":{"command":"ls"}}`)
	if out != "{}" {
		t.Errorf("expected {} for empty registry, got %s", out)
	}
}

func TestDispatchBlockDecision(t *testing.T) {
	Reset()
	Register("PreToolUse", Entry{
		Matcher: "Bash",
		Handler: func(e, t string, ti map[string]any, r string) HookResult {
			return Block("dangerous command")
		},
		Critical: true,
	})
	out := Dispatch("PreToolUse", `{"tool_name":"Bash","tool_input":{"command":"rm -rf /"}}`)
	if !strings.Contains(out, `"decision":"block"`) || !strings.Contains(out, `"reason":"dangerous command"`) {
		t.Errorf("expected block decision with reason, got %s", out)
	}
}

func TestDispatchBlockOverridesApprove(t *testing.T) {
	Reset()
	Register("PreToolUse", Entry{
		Handler:  func(e, t string, ti map[string]any, r string) HookResult { return Approve() },
		Critical: true,
	})
	Register("PreToolUse", Entry{
		Handler:  func(e, t string, ti map[string]any, r string) HookResult { return Block("nope") },
		Critical: true,
	})
	out := Dispatch("PreToolUse", `{}`)
	if !strings.Contains(out, `"decision":"block"`) {
		t.Errorf("block should win over approve, got %s", out)
	}
}

func TestDispatchMatcherFiltering(t *testing.T) {
	Reset()
	called := false
	Register("PreToolUse", Entry{
		Matcher: "Bash",
		Handler: func(e, t string, ti map[string]any, r string) HookResult {
			called = true
			return Allow()
		},
		Critical: true,
	})
	Dispatch("PreToolUse", `{"tool_name":"Write","tool_input":{}}`)
	if called {
		t.Error("handler matching Bash should not fire for Write")
	}
	Dispatch("PreToolUse", `{"tool_name":"Bash","tool_input":{}}`)
	if !called {
		t.Error("handler matching Bash should fire for Bash")
	}
}

func TestDispatchUserPromptSubmitPassthrough(t *testing.T) {
	Reset()
	Register("UserPromptSubmit", Entry{
		Handler: func(e, t string, ti map[string]any, r string) HookResult { return TextResult("hello") },
	})
	Register("UserPromptSubmit", Entry{
		Handler: func(e, t string, ti map[string]any, r string) HookResult { return TextResult("world") },
	})
	out := Dispatch("UserPromptSubmit", `{}`)
	if out != "hello\nworld" {
		t.Errorf("expected 'hello\\nworld', got %q", out)
	}
}

func TestDispatchPanicRecovery(t *testing.T) {
	Reset()
	Register("PreToolUse", Entry{
		Handler: func(e, t string, ti map[string]any, r string) HookResult {
			panic("boom")
		},
		Critical: true,
	})
	out := Dispatch("PreToolUse", `{}`)
	if out != "{}" {
		t.Errorf("panicked handler should fail-open, got %s", out)
	}
}

func TestDispatchMalformedJSON(t *testing.T) {
	Reset()
	out := Dispatch("PreToolUse", `not-json`)
	if out != "{}" {
		t.Errorf("malformed JSON should return empty, got %s", out)
	}
}

func TestDispatchUpdatedInput(t *testing.T) {
	Reset()
	Register("PreToolUse", Entry{
		Matcher: "Bash",
		Handler: func(e, t string, ti map[string]any, r string) HookResult {
			return HookResult{UpdatedInput: map[string]any{"command": "safe"}}
		},
	})
	out := Dispatch("PreToolUse", `{"tool_name":"Bash","tool_input":{"command":"risky"}}`)
	if !strings.Contains(out, `"hookSpecificOutput"`) || !strings.Contains(out, `"updatedInput"`) {
		t.Errorf("expected hookSpecificOutput rewrite, got %s", out)
	}
}
