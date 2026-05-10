package ws

import "time"

// heartbeat sends a {type:"ping", ts:epoch_ms} frame every 15 seconds.
// Returns when c.ctx is cancelled.
func (c *Conn) heartbeat() error {
	ticker := time.NewTicker(15 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-c.ctx.Done():
			return nil
		case <-ticker.C:
			c.send(outPing{Type: "ping", Ts: epochMs()})
		}
	}
}
