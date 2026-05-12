package tmuxctl

import (
	"context"
	"errors"
	"strconv"
	"strings"
)

func (c *Client) ResizePane(ctx context.Context, target string, cols, rows int) error {
	_, err := c.Run(ctx, "resize-pane", "-t", target, "-x", strconv.Itoa(cols), "-y", strconv.Itoa(rows))
	return err
}

// SelectLayout applies a tmux layout preset. Empty layout falls back to
// "even-horizontal" to match Python's default.
func (c *Client) SelectLayout(ctx context.Context, target, layout string) error {
	if layout == "" {
		layout = "even-horizontal"
	}
	_, err := c.Run(ctx, "select-layout", "-t", target, layout)
	return err
}

// SelectPaneByDirection moves focus by direction: left/right/up/down (case-insensitive).
func (c *Client) SelectPaneByDirection(ctx context.Context, target, direction string) error {
	flag, ok := directionFlag(strings.ToLower(direction))
	if !ok {
		return errors.New("tmuxctl: invalid direction: " + direction)
	}
	_, err := c.Run(ctx, "select-pane", "-t", target, flag)
	return err
}

func directionFlag(d string) (string, bool) {
	switch d {
	case "left":
		return "-L", true
	case "right":
		return "-R", true
	case "up":
		return "-U", true
	case "down":
		return "-D", true
	}
	return "", false
}

// SelectPane focuses a specific pane by tmux target (e.g., "session:0.1").
func (c *Client) SelectPane(ctx context.Context, target string) error {
	_, err := c.Run(ctx, "select-pane", "-t", target)
	return err
}

// LayoutOf returns the window-layout string. Used by fit-mode to save/restore
// layouts when the frontend resizes panes.
func (c *Client) LayoutOf(ctx context.Context, target string) (string, error) {
	out, ok := c.RunOK(ctx, "display-message", "-t", target, "-p", "#{window_layout}")
	if !ok {
		return "", nil
	}
	return strings.TrimSpace(out), nil
}
