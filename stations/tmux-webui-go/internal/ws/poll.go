package ws

import (
	"math"
	"time"
)

// Adaptive backoff parameters (seconds → converted to durations).
const (
	pollMin  = 400 * time.Millisecond
	pollMax  = 2000 * time.Millisecond
	pollStep = 400 * time.Millisecond
)

// pollLoop runs an adaptive-interval ticker:
//   - On pane content change → send outOutput + reset interval to 0.4 s
//   - No change → step up by 0.4 s until 2.0 s
//
// A metrics frame is emitted every ⌈metricsInterval/pollInterval⌉ ticks.
// pollLoop returns when c.ctx is cancelled.
func (c *Conn) pollLoop() error {
	interval := pollMin
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	snapshot := make(map[string]string)
	tickCount := 0

	metricsEvery := metricsTickEvery(c.hub.cfg.MetricsInterval, pollMin.Seconds())

	for {
		select {
		case <-c.ctx.Done():
			return nil
		case <-ticker.C:
			tickCount++
			changed := c.pollPanes(snapshot)

			if changed {
				interval = pollMin
			} else {
				interval = stepUp(interval)
			}
			// Reset ticker to new interval.
			ticker.Reset(interval)

			// Emit metrics every N ticks.
			if tickCount%metricsEvery == 0 {
				c.send(outMetrics{Type: "metrics", Metrics: map[string]any{}})
			}
		}
	}
}

// pollPanes captures all panes, diffs against snapshot, sends outOutput if any
// pane changed, and updates snapshot. Returns true if any content changed.
func (c *Conn) pollPanes(snapshot map[string]string) bool {
	panes, err := c.hub.tx.ListPanes(c.ctx, c.session)
	if err != nil || len(panes) == 0 {
		return false
	}

	changed := make(map[string]string)
	for _, p := range panes {
		content, err := c.hub.tx.CapturePane(c.ctx, c.session+":"+p.ID, c.hub.cfg.CaptureLines)
		if err != nil {
			continue
		}
		if prev, ok := snapshot[p.ID]; !ok || prev != content {
			changed[p.ID] = content
			snapshot[p.ID] = content
		}
	}

	if len(changed) == 0 {
		return false
	}
	c.send(outOutput{Type: "output", Panes: changed})
	return true
}

// stepUp advances interval by one step, capped at pollMax.
func stepUp(d time.Duration) time.Duration {
	next := d + pollStep
	if next > pollMax {
		return pollMax
	}
	return next
}

// metricsTickEvery computes ⌈metricsInterval / pollInterval⌉ (minimum 1).
func metricsTickEvery(metricsInterval, pollInterval float64) int {
	if pollInterval <= 0 {
		return 1
	}
	n := int(math.Ceil(metricsInterval / pollInterval))
	if n < 1 {
		n = 1
	}
	return n
}
