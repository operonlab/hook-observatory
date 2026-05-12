package ws

import (
	"sort"
	"strings"
)

// handleKeyWithFSM runs the prefix-key finite-state machine and dispatches
// the key to tmux accordingly.
//
// FSM transitions:
//
//	idle  + key==prefixKey → waiting=true, send prefix_active, return
//	waiting + any key     → lookup binding; exec cmd or send raw key; waiting=false
//	idle  + other key     → send raw key
//
// handleKeyWithFSM implements Py server.py:697-734's 5-case FSM:
//
//  1. prefixWaiting=true  → look up binding; exec or send raw (literal=false)
//  2. combo == prefix key → enter prefix mode, send prefix_active
//  3. has modifiers       → send-keys literal=false (so "C-a" is interpreted)
//  4. single char, no mod → send-keys literal=true  (so "$" or "?" is sent verbatim)
//  5. fallback            → send-keys literal=false
func (c *Conn) handleKeyWithFSM(msg *InboundMsg) error {
	if msg.Key == "" {
		return nil
	}
	hasMods := false
	for _, m := range msg.Modifiers {
		switch strings.ToLower(m) {
		case "ctrl", "c", "alt", "m", "shift", "s":
			hasMods = true
		}
	}
	combo := buildKeySpec(msg.Key, msg.Modifiers)
	target := c.paneTarget(msg.Pane)

	// Case 1: in-prefix state — second key consumes binding.
	if c.prefixWaiting {
		c.prefixWaiting = false
		cmd := c.hub.pc.Lookup(c.ctx, combo)
		if cmd != "" {
			return c.executePrefixCmd(target, cmd)
		}
		// No binding — send raw (literal=false).
		return c.hub.tx.SendKey(c.ctx, target, combo)
	}

	// Case 2: this press IS the prefix.
	if combo == c.hub.pc.Key(c.ctx) {
		c.prefixWaiting = true
		c.send(outPrefixActive{Type: "prefix_active"})
		return nil
	}

	// Case 3: modifiers present → literal=false so tmux interprets the combo.
	if hasMods {
		return c.hub.tx.SendKey(c.ctx, target, combo)
	}

	// Case 4: single character, no modifiers → literal=true so symbols
	// like "$", "?", "{" reach the program verbatim.
	if utf8RuneCount(msg.Key) == 1 {
		return c.hub.tx.SendText(c.ctx, target, msg.Key)
	}

	// Case 5: named key (Up, Tab, F1, ...) → literal=false.
	return c.hub.tx.SendKey(c.ctx, target, msg.Key)
}

// utf8RuneCount returns the number of runes in s without importing unicode/utf8
// at the top of the file (keep the prefix_fsm imports minimal).
func utf8RuneCount(s string) int {
	n := 0
	for range s {
		n++
	}
	return n
}

// executePrefixCmd runs a tmux prefix binding command.
// Common bindings map directly to tmuxctl methods; unrecognised commands
// are forwarded via send-keys as a best-effort fallback.
func (c *Conn) executePrefixCmd(target, cmd string) error {
	parts := strings.Fields(cmd)
	if len(parts) == 0 {
		return nil
	}
	switch parts[0] {
	case "split-window":
		_, err := c.hub.tx.Run(c.ctx, append([]string{"split-window", "-t", target}, parts[1:]...)...)
		return err
	case "new-window":
		return c.hub.tx.NewWindow(c.ctx, c.session)
	case "kill-pane":
		_, err := c.hub.tx.Run(c.ctx, "kill-pane", "-t", target)
		return err
	case "select-pane":
		if len(parts) >= 2 {
			_, err := c.hub.tx.Run(c.ctx, "select-pane", "-t", target, parts[1])
			return err
		}
		return c.hub.tx.SelectPane(c.ctx, target)
	case "select-window":
		_, err := c.hub.tx.Run(c.ctx, append([]string{"select-window", "-t", c.session}, parts[1:]...)...)
		return err
	case "resize-pane":
		_, err := c.hub.tx.Run(c.ctx, append([]string{"resize-pane", "-t", target}, parts[1:]...)...)
		return err
	case "next-window":
		_, err := c.hub.tx.Run(c.ctx, "next-window", "-t", c.session)
		return err
	case "previous-window":
		_, err := c.hub.tx.Run(c.ctx, "previous-window", "-t", c.session)
		return err
	case "last-window":
		_, err := c.hub.tx.Run(c.ctx, "last-window", "-t", c.session)
		return err
	default:
		// Fallback: run arbitrary tmux command.
		_, err := c.hub.tx.Run(c.ctx, parts...)
		return err
	}
}

// buildKeySpec constructs a tmux key specification from a base key and a list
// of modifier strings. Modifiers are deduplicated and sorted for stability.
//
// Supported modifier strings (case-insensitive):
//
//	"Ctrl" / "C"  → "C-" prefix
//	"Alt"  / "M"  → "M-" prefix
//	"Shift"/ "S"  → "S-" prefix
//
// Example: key="x", modifiers=["Ctrl","Shift"] → "C-S-x"
func buildKeySpec(key string, modifiers []string) string {
	if len(modifiers) == 0 {
		return key
	}

	set := make(map[string]bool)
	for _, m := range modifiers {
		switch strings.ToLower(m) {
		case "ctrl", "c":
			set["C"] = true
		case "alt", "m":
			set["M"] = true
		case "shift", "s":
			set["S"] = true
		}
	}

	// Stable ordering: C → M → S
	order := []string{"C", "M", "S"}
	var parts []string
	for _, p := range order {
		if set[p] {
			parts = append(parts, p)
		}
	}
	sort.Strings(parts) // redundant given fixed order, but keeps it explicit

	if len(parts) == 0 {
		return key
	}
	return strings.Join(parts, "-") + "-" + key
}
