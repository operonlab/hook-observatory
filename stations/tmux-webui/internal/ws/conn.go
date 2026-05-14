package ws

import (
	"context"
	"encoding/json"
	"sync/atomic"
	"time"

	"github.com/coder/websocket"
	"golang.org/x/sync/errgroup"

	"github.com/operonlab/tmux-webui/internal/tmuxctl"
)

const outChanSize = 64

// envelope is a pre-marshalled JSON frame ready to write on the wire.
type envelope []byte

// Conn is the per-WebSocket-connection state. It must be created via
// Hub.UpgradeHandler; never construct directly.
type Conn struct {
	hub     *Hub
	ws      *websocket.Conn
	session string

	ctx    context.Context
	cancel context.CancelFunc

	outChan chan envelope

	// fit-mode state (see fit.go)
	fitMode         bool
	originalLayouts map[int]string

	// prefix FSM state (see prefix_fsm.go)
	prefixWaiting bool

	// activeWindow tracks the currently-displayed tmux window index.
	// Updated by reader goroutine (handleSwitchWindow / handleNewWindow /
	// handleCloseWindow) and read by pollLoop. Atomic for cross-goroutine
	// safety without holding a mutex during the long-running poll.
	activeWindow atomic.Int32

	// snapshotDirty asks pollLoop to clear its content cache on next tick.
	// Set after window switches so all panes' output gets re-sent to the
	// frontend (matches Python's last_contents.clear() behaviour).
	snapshotDirty atomic.Bool
}

// newConn allocates a Conn. ctx should be the request context or a derived ctx.
func newConn(parent context.Context, h *Hub, ws *websocket.Conn, session string) *Conn {
	ctx, cancel := context.WithCancel(parent)
	return &Conn{
		hub:             h,
		ws:              ws,
		session:         session,
		ctx:             ctx,
		cancel:          cancel,
		outChan:         make(chan envelope, outChanSize),
		originalLayouts: make(map[int]string),
	}
}

// send marshals msg as JSON and enqueues it for the writer goroutine.
// Non-blocking: drops the message on overflow rather than blocking the caller.
func (c *Conn) send(msg any) {
	b, err := json.Marshal(msg)
	if err != nil {
		return
	}
	select {
	case c.outChan <- envelope(b):
	case <-c.ctx.Done():
	default:
		// drop on overflow — a slow client must not stall the poll loop
	}
}

// sendInitial pushes the opening windows + panes + metrics frames.
func (c *Conn) sendInitial(ctx context.Context) {
	windows, _ := c.hub.tx.ListWindows(ctx, c.session)
	if windows == nil {
		windows = []tmuxctl.Window{}
	}
	active := 0
	for _, w := range windows {
		if w.Active == 1 {
			active = w.Index
			break
		}
	}
	c.activeWindow.Store(int32(active))
	c.send(outWindows{Type: "windows", Windows: windows, Active: active})

	panes, _ := c.hub.tx.ListPanes(ctx, c.session)
	if panes == nil {
		panes = []tmuxctl.Pane{}
	}
	c.send(outPanes{Type: "panes", Panes: visiblePanes(panes, active)})

	c.send(outMetrics{Type: "metrics", Metrics: c.hub.prov.Collect(ctx)})
}

// visiblePanes filters panes to those in the given active window.
// activeWin == 0 (default tmux pane-base-index is 1) means "no filter" —
// matches the Python `active_window is None` early-return branch.
func visiblePanes(panes []tmuxctl.Pane, activeWin int) []tmuxctl.Pane {
	if activeWin <= 0 {
		return panes
	}
	out := make([]tmuxctl.Pane, 0, len(panes))
	for _, p := range panes {
		if p.Window == activeWin {
			out = append(out, p)
		}
	}
	return out
}

// Run starts the four goroutines and blocks until all exit (errgroup).
// On return the connection is fully torn down (layout restore + hub remove + ws close).
func (c *Conn) Run() {
	defer func() {
		c.cancel()
		c.restoreLayouts()
		c.hub.Remove(c)
		c.ws.Close(websocket.StatusNormalClosure, "bye")
	}()

	// Send initial state synchronously before starting goroutines so the
	// client gets its first frame before any poll tick races in.
	c.sendInitial(c.ctx)

	eg, ctx := errgroup.WithContext(c.ctx)
	_ = ctx // used by individual goroutines via c.ctx (already derived)

	eg.Go(func() error { return c.pollLoop() })
	eg.Go(func() error { return c.heartbeat() })
	eg.Go(func() error { return c.reader() })
	eg.Go(func() error { c.writer(); return nil })

	// Wait for any goroutine to return, then cancel the rest via deferred cancel.
	_ = eg.Wait()
}

// epochMs returns current Unix time in milliseconds.
func epochMs() int64 { return time.Now().UnixMilli() }
