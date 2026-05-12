package tmuxctl

import (
	"context"
	"fmt"
	"io"
	"os/exec"
)

// sendKeysLimit mirrors libs/tmux-lib/tmux_lib/primitives.py:_SEND_KEYS_LIMIT.
// Texts longer than this go through load-buffer + paste-buffer to avoid ARG_MAX
// and to preserve multi-line behavior identical to the Python implementation.
const sendKeysLimit = 512

// SendText delivers literal text to a pane.
// Default buffer name is "_webui_paste" (matches Python).
func (c *Client) SendText(ctx context.Context, target, text string) error {
	return c.SendTextWithBuf(ctx, target, text, "_webui_paste")
}

func (c *Client) SendTextWithBuf(ctx context.Context, target, text, buf string) error {
	if len(text) > sendKeysLimit {
		return c.pasteText(ctx, target, text, buf)
	}
	_, err := c.Run(ctx, "send-keys", "-t", target, "-l", text)
	return err
}

// SendKey sends a non-literal key spec (e.g. "Enter", "C-c", "Up", "M-x").
func (c *Client) SendKey(ctx context.Context, target, key string) error {
	_, err := c.Run(ctx, "send-keys", "-t", target, key)
	return err
}

// SendEnter is a convenience for the most common single-key send.
func (c *Client) SendEnter(ctx context.Context, target string) error {
	return c.SendKey(ctx, target, "Enter")
}

func (c *Client) pasteText(ctx context.Context, target, text, buf string) error {
	cmd := exec.CommandContext(ctx, c.bin, "load-buffer", "-b", buf, "-")
	stdin, err := cmd.StdinPipe()
	if err != nil {
		return fmt.Errorf("load-buffer pipe: %w", err)
	}
	if err := cmd.Start(); err != nil {
		return fmt.Errorf("load-buffer start: %w", err)
	}
	if _, err := io.WriteString(stdin, text); err != nil {
		_ = stdin.Close()
		_ = cmd.Wait()
		return fmt.Errorf("load-buffer write: %w", err)
	}
	if err := stdin.Close(); err != nil {
		_ = cmd.Wait()
		return fmt.Errorf("load-buffer close: %w", err)
	}
	if err := cmd.Wait(); err != nil {
		return fmt.Errorf("load-buffer wait: %w", err)
	}
	if _, err := c.Run(ctx, "paste-buffer", "-b", buf, "-t", target, "-d", "-p"); err != nil {
		_, _ = c.Run(ctx, "delete-buffer", "-b", buf)
		return fmt.Errorf("paste-buffer: %w", err)
	}
	return nil
}
