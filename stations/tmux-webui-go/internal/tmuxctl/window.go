package tmuxctl

import (
	"context"
	"fmt"
)

func (c *Client) NewWindow(ctx context.Context, session string) error {
	_, err := c.Run(ctx, "new-window", "-t", session)
	return err
}

func (c *Client) KillWindow(ctx context.Context, session string, window int) error {
	_, err := c.Run(ctx, "kill-window", "-t", fmt.Sprintf("%s:%d", session, window))
	return err
}
