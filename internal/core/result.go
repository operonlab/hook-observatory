package core

// HookResult mirrors handlers/base.py HookResult.
//
// Decision semantics:
//
//	"block"   → veto the tool call (highest priority in merge)
//	"approve" → pre-approve (bypasses user prompts)
//	""        → passthrough (default)
//
// Text vs Message:
//
//	Text    — raw passthrough content (UserPromptSubmit injection)
//	Message — shown in Claude Code UI
//
// UpdatedInput rewrites the tool_input (PreToolUse rewrite).
type HookResult struct {
	Decision     string
	Reason       string
	Message      string
	Text         string
	UpdatedInput map[string]any
}

// Allow returns a no-op result (passthrough).
func Allow() HookResult { return HookResult{} }

// Block returns a block decision with reason.
func Block(reason string) HookResult {
	return HookResult{Decision: "block", Reason: reason}
}

// Approve returns an approve decision.
func Approve() HookResult {
	return HookResult{Decision: "approve"}
}

// Message returns a result carrying a UI message only.
func Message(msg string) HookResult {
	return HookResult{Message: msg}
}

// TextResult returns a passthrough-text result (for UserPromptSubmit).
func TextResult(text string) HookResult {
	return HookResult{Text: text}
}

// IsBlock reports whether the result is a block decision.
func (r HookResult) IsBlock() bool { return r.Decision == "block" }

// IsApprove reports whether the result is an approve decision.
func (r HookResult) IsApprove() bool { return r.Decision == "approve" }

// accumulator holds the merged state across multiple handler results.
// Mirrors handlers/__init__.py _merge_result state dict.
type accumulator struct {
	Decision         string
	Reason           string
	Messages         []string
	PassthroughParts []string
	UpdatedInput     map[string]any
}

// merge folds a single HookResult into the accumulator.
// Priority: block > approve > passthrough.
func (a *accumulator) merge(r HookResult) {
	switch r.Decision {
	case "block":
		a.Decision = "block"
		a.Reason = r.Reason
	case "approve":
		if a.Decision != "block" {
			a.Decision = "approve"
		}
	}
	if r.Message != "" {
		a.Messages = append(a.Messages, r.Message)
	}
	if r.Text != "" {
		a.PassthroughParts = append(a.PassthroughParts, r.Text)
	}
	if r.UpdatedInput != nil {
		a.UpdatedInput = r.UpdatedInput
	}
}
