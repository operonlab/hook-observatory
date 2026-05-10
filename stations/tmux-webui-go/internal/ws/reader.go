package ws

import (
	"encoding/json"

	"github.com/coder/websocket"
)

// reader blocks on wsConn.Read, parses each inbound frame as JSON, and
// dispatches to the appropriate handler. It returns when ctx is cancelled,
// the connection closes, or an unrecoverable read error occurs.
func (c *Conn) reader() error {
	for {
		_, data, err := c.ws.Read(c.ctx)
		if err != nil {
			// ctx cancellation or connection close — normal exit
			return nil
		}

		var msg InboundMsg
		if err := json.Unmarshal(data, &msg); err != nil {
			c.send(newError("invalid JSON: " + err.Error()))
			continue
		}

		if err := c.dispatch(&msg); err != nil {
			c.send(newInputError(err.Error()))
		}
	}
}

// dispatch routes the inbound message to the correct handler.
func (c *Conn) dispatch(msg *InboundMsg) error {
	switch msg.Type {
	case "focus":
		return c.handleFocus(msg)
	case "input":
		return c.handleInput(msg)
	case "key":
		return c.handleKey(msg)
	case "switch_window":
		return c.handleSwitchWindow(msg)
	case "new_window":
		return c.handleNewWindow(msg)
	case "close_window":
		return c.handleCloseWindow(msg)
	case "fit":
		return c.handleFit(msg)
	case "fit_enable":
		c.fitMode = true
		return nil
	case "fit_disable":
		c.fitMode = false
		c.restoreLayouts()
		return nil
	case "select_pane_direction":
		return c.handleSelectPaneDirection(msg)
	case "autocomplete":
		c.send(outAutocomplete{Type: "autocomplete", Results: []string{}})
		return nil
	case "refresh_panes":
		return c.handleRefreshPanes()
	case "pong":
		// client heartbeat reply; discard
		return nil
	default:
		c.send(newError("unknown message type: " + msg.Type))
		return nil
	}
}

// ─── Individual message handlers ──────────────────────────────────────────────

func (c *Conn) handleFocus(msg *InboundMsg) error {
	target := c.paneTarget(msg.Pane)
	return c.hub.tx.SelectPane(c.ctx, target)
}

func (c *Conn) handleInput(msg *InboundMsg) error {
	target := c.paneTarget(msg.Pane)
	return c.hub.tx.SendText(c.ctx, target, msg.Text)
}

func (c *Conn) handleKey(msg *InboundMsg) error {
	return c.handleKeyWithFSM(msg)
}

func (c *Conn) handleSwitchWindow(msg *InboundMsg) error {
	_, err := c.hub.tx.Run(c.ctx, "select-window", "-t",
		c.session+":"+itoa(msg.Window))
	return err
}

func (c *Conn) handleNewWindow(_ *InboundMsg) error {
	return c.hub.tx.NewWindow(c.ctx, c.session)
}

func (c *Conn) handleCloseWindow(msg *InboundMsg) error {
	return c.hub.tx.KillWindow(c.ctx, c.session, msg.Window)
}

func (c *Conn) handleSelectPaneDirection(msg *InboundMsg) error {
	target := c.paneTarget(msg.Pane)
	return c.hub.tx.SelectPaneByDirection(c.ctx, target, msg.Direction)
}

func (c *Conn) handleRefreshPanes() error {
	panes, err := c.hub.tx.ListPanes(c.ctx, c.session)
	if err != nil || panes == nil {
		panes = nil
	}
	windows, _ := c.hub.tx.ListWindows(c.ctx, c.session)
	active := 0
	for _, w := range windows {
		if w.Active == 1 {
			active = w.Index
			break
		}
	}
	if windows != nil {
		c.send(outWindows{Type: "windows", Windows: windows, Active: active})
	}
	if panes != nil {
		c.send(outPanes{Type: "panes", Panes: panes})
	}
	return nil
}

// paneTarget builds a tmux target string from pane id.
// pane id format: "winIdx.paneIdx" (e.g. "0.1") → "session:0.1"
func (c *Conn) paneTarget(pane string) string {
	if pane == "" {
		return c.session
	}
	return c.session + ":" + pane
}

// itoa converts int to string without importing strconv in reader.go
// (strconv is already used in other files; keep reader.go self-contained).
func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	result := make([]byte, 0, 10)
	neg := n < 0
	if neg {
		n = -n
	}
	for n > 0 {
		result = append([]byte{byte('0' + n%10)}, result...)
		n /= 10
	}
	if neg {
		result = append([]byte{'-'}, result...)
	}
	return string(result)
}

// sendWindowsAndPanes is a helper used when the window/pane state changes.
func (c *Conn) sendWindowsAndPanes() {
	windows, _ := c.hub.tx.ListWindows(c.ctx, c.session)
	if windows == nil {
		return
	}
	active := 0
	for _, w := range windows {
		if w.Active == 1 {
			active = w.Index
			break
		}
	}
	c.send(outWindows{Type: "windows", Windows: windows, Active: active})
	panes, _ := c.hub.tx.ListPanes(c.ctx, c.session)
	if panes != nil {
		c.send(outPanes{Type: "panes", Panes: panes})
	}
}

// Ensure websocket import used (Read call in reader loop).
var _ = websocket.MessageText
