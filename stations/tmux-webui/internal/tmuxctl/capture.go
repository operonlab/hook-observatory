package tmuxctl

import (
	"context"
	"strconv"
)

// CapturePane returns the visible content of a pane with ANSI escape sequences
// (-e) so the frontend ANSI parser sees colors. lines is the scrollback depth;
// 0 falls back to 150 (matches Python default).
func (c *Client) CapturePane(ctx context.Context, target string, lines int) (string, error) {
	if lines <= 0 {
		lines = 150
	}
	out, ok := c.RunOK(ctx, "capture-pane", "-t", target, "-p", "-S", strconv.Itoa(-lines), "-e")
	if !ok {
		return "", nil
	}
	return out, nil
}
