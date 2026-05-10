package ws

import (
	"net/http"

	"github.com/coder/websocket"
)

// UpgradeHandler returns an http.Handler that upgrades HTTP connections to
// WebSocket and runs the connection lifecycle.
//
// It expects a "session" query parameter; missing or empty session yields 400.
//
// Usage in server.go:
//
//	mux.Handle("/ws", hub.UpgradeHandler())
func (h *Hub) UpgradeHandler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		session := r.URL.Query().Get("session")
		if session == "" {
			http.Error(w, "missing ?session= parameter", http.StatusBadRequest)
			return
		}

		wsConn, err := websocket.Accept(w, r, &websocket.AcceptOptions{
			// Allow all origins for a local tool; tighten in production.
			InsecureSkipVerify: true,
		})
		if err != nil {
			// Accept already wrote an HTTP error response.
			return
		}

		conn := newConn(r.Context(), h, wsConn, session)
		h.add(conn)

		// Run blocks until the connection is fully torn down.
		conn.Run()
	})
}
