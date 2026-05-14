package ws

import (
	"encoding/json"
	"sync"

	"github.com/operonlab/tmux-webui/internal/config"
	"github.com/operonlab/tmux-webui/internal/metrics"
	"github.com/operonlab/tmux-webui/internal/prefix"
	"github.com/operonlab/tmux-webui/internal/tmuxctl"
)

// Hub manages all active WebSocket connections.
// Safe for concurrent use.
type Hub struct {
	cfg   *config.Config
	tx    *tmuxctl.Client
	pc    *prefix.Cache
	prov  metrics.Provider
	conns sync.Map // map[*Conn]struct{}
}

// NewHub constructs a Hub. cfg, tx, pc, and prov must not be nil.
// Pass metrics.NewStub() for prov when metrics are disabled.
func NewHub(cfg *config.Config, tx *tmuxctl.Client, pc *prefix.Cache, prov metrics.Provider) *Hub {
	return &Hub{cfg: cfg, tx: tx, pc: pc, prov: prov}
}

// add registers a connection.
func (h *Hub) add(c *Conn) { h.conns.Store(c, struct{}{}) }

// Remove unregisters a connection.
func (h *Hub) Remove(c *Conn) { h.conns.Delete(c) }

// Broadcast marshals msg as JSON and sends it to every registered connection.
// Slow or closed connections are dropped non-blocking (mirroring Conn.send).
func (h *Hub) Broadcast(msg any) {
	b, err := json.Marshal(msg)
	if err != nil {
		return
	}
	h.conns.Range(func(key, _ any) bool {
		c := key.(*Conn)
		select {
		case c.outChan <- envelope(b):
		default:
			// drop on overflow; connection will eventually close itself
		}
		return true
	})
}

// BroadcastTTS is a convenience wrapper for Hub.Broadcast with a TTS payload.
func (h *Hub) BroadcastTTS(id, text string) {
	h.Broadcast(outTTS{Type: "tts", ID: id, Text: text})
}
