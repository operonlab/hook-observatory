package ws

import "strings"

// handleFit handles a "fit" inbound message.
//
// When fitMode is true:
//  1. Determine the window index from pane id (e.g. "0.1" → winIdx=0).
//  2. If no saved layout for that window, snapshot the current layout first.
//  3. Resize the target pane to (cols, rows).
//
// When fitMode is false the message is silently ignored.
func (c *Conn) handleFit(msg *InboundMsg) error {
	if !c.fitMode {
		return nil
	}
	if msg.Pane == "" {
		return nil
	}

	target := c.paneTarget(msg.Pane)
	winIdx := winIndexFromPaneID(msg.Pane)

	// Save original layout before first resize of this window.
	if _, saved := c.originalLayouts[winIdx]; !saved {
		layout, err := c.hub.tx.LayoutOf(c.ctx, target)
		if err == nil && layout != "" {
			c.originalLayouts[winIdx] = layout
		}
	}

	return c.hub.tx.ResizePane(c.ctx, target, msg.Cols, msg.Rows)
}

// restoreLayouts restores all windows whose layouts were saved during fit-mode.
// Called on fit_disable or connection teardown.
func (c *Conn) restoreLayouts() {
	for winIdx, layout := range c.originalLayouts {
		target := c.session + ":" + itoa(winIdx)
		_ = c.hub.tx.SelectLayout(c.ctx, target, layout)
	}
	c.originalLayouts = make(map[int]string)
}

// winIndexFromPaneID extracts the window index from a pane id like "0.1".
// Falls back to 0 on any parse error.
func winIndexFromPaneID(paneID string) int {
	parts := strings.SplitN(paneID, ".", 2)
	if len(parts) == 0 {
		return 0
	}
	n := 0
	for _, ch := range parts[0] {
		if ch < '0' || ch > '9' {
			return 0
		}
		n = n*10 + int(ch-'0')
	}
	return n
}
