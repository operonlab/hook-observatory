package core

import "testing"

func TestMergePriority(t *testing.T) {
	a := &accumulator{}
	a.merge(Approve())
	if a.Decision != "approve" {
		t.Fatalf("expected approve, got %q", a.Decision)
	}
	a.merge(Block("danger"))
	if a.Decision != "block" || a.Reason != "danger" {
		t.Fatalf("block must win over approve, got decision=%q reason=%q", a.Decision, a.Reason)
	}
	// Later approve must not override block
	a.merge(Approve())
	if a.Decision != "block" {
		t.Fatalf("approve must not override block, got %q", a.Decision)
	}
}

func TestMergeMessages(t *testing.T) {
	a := &accumulator{}
	a.merge(Message("one"))
	a.merge(Message("two"))
	if len(a.Messages) != 2 || a.Messages[0] != "one" || a.Messages[1] != "two" {
		t.Fatalf("messages not accumulated: %v", a.Messages)
	}
}

func TestMergePassthrough(t *testing.T) {
	a := &accumulator{}
	a.merge(TextResult("hello"))
	a.merge(TextResult("world"))
	if len(a.PassthroughParts) != 2 {
		t.Fatalf("passthrough parts not accumulated: %v", a.PassthroughParts)
	}
}

func TestMergeUpdatedInput(t *testing.T) {
	a := &accumulator{}
	a.merge(HookResult{UpdatedInput: map[string]any{"command": "rewritten"}})
	if a.UpdatedInput["command"] != "rewritten" {
		t.Fatalf("updated input not captured: %v", a.UpdatedInput)
	}
}
