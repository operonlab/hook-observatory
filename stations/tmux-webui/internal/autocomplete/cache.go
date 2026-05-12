package autocomplete

import (
	"context"
	"log"
	"sync"
	"time"
)

const defaultRefreshInterval = 5 * time.Minute

// Stats reports how many items are currently cached.
type Stats struct {
	Skills     int `json:"skills"`
	Commands   int `json:"commands"`
	Agents     int `json:"agents"`
	MCPServers int `json:"mcp_servers"`
}

// ResourceCache holds a snapshot of scanned Claude resources and refreshes
// them periodically using a time.Ticker. All fields are protected by a Mutex.
type ResourceCache struct {
	mu       sync.Mutex
	skills   []Item
	commands []Item
	agents   []Item
	mcps     []Item

	scanner  *ClaudeDirScanner // nil when Claude scanning is disabled
	interval time.Duration
	ticker   *time.Ticker
	done     chan struct{}
}

// newResourceCache creates a cache and starts the background refresh ticker.
// Pass nil scanner to disable Claude directory scanning.
func newResourceCache(scanner *ClaudeDirScanner, interval time.Duration) *ResourceCache {
	if interval <= 0 {
		interval = defaultRefreshInterval
	}
	c := &ResourceCache{
		scanner:  scanner,
		interval: interval,
		done:     make(chan struct{}),
	}

	// Initial synchronous scan so the cache is warm on first Complete() call.
	c.doScan()

	// Start background ticker.
	c.ticker = time.NewTicker(interval)
	go c.loop()

	return c
}

// loop runs the periodic refresh in a goroutine until Close() is called.
func (c *ResourceCache) loop() {
	for {
		select {
		case <-c.ticker.C:
			c.doScan()
		case <-c.done:
			return
		}
	}
}

// doScan calls the scanner (if configured) and updates the cache atomically.
func (c *ResourceCache) doScan() {
	if c.scanner == nil {
		return
	}

	items := c.scanner.Scan(context.Background())

	var skills, commands, agents, mcps []Item
	for _, it := range items {
		switch it.Type {
		case "skill":
			skills = append(skills, it)
		case "command":
			commands = append(commands, it)
		case "agent":
			agents = append(agents, it)
		case "mcp":
			mcps = append(mcps, it)
		}
	}

	c.mu.Lock()
	c.skills = skills
	c.commands = commands
	c.agents = agents
	c.mcps = mcps
	c.mu.Unlock()

	log.Printf("autocomplete: scan complete — %d skills, %d commands, %d agents, %d MCP servers",
		len(skills), len(commands), len(agents), len(mcps))
}

// slashItems returns a copy of skills + commands (for "/" prefix queries).
func (c *ResourceCache) slashItems() []Item {
	c.mu.Lock()
	defer c.mu.Unlock()
	out := make([]Item, 0, len(c.skills)+len(c.commands))
	out = append(out, c.skills...)
	out = append(out, c.commands...)
	return out
}

// atItems returns a copy of agents + mcp servers (for "@" prefix queries).
func (c *ResourceCache) atItems() []Item {
	c.mu.Lock()
	defer c.mu.Unlock()
	out := make([]Item, 0, len(c.agents)+len(c.mcps))
	out = append(out, c.agents...)
	out = append(out, c.mcps...)
	return out
}

// snapshot returns current stats without triggering a scan.
func (c *ResourceCache) snapshot() Stats {
	c.mu.Lock()
	defer c.mu.Unlock()
	return Stats{
		Skills:     len(c.skills),
		Commands:   len(c.commands),
		Agents:     len(c.agents),
		MCPServers: len(c.mcps),
	}
}

// forceRefresh triggers an immediate synchronous scan and returns updated stats.
func (c *ResourceCache) forceRefresh() Stats {
	c.doScan()
	return c.snapshot()
}

// Close stops the background ticker goroutine.
func (c *ResourceCache) Close() {
	if c.ticker != nil {
		c.ticker.Stop()
	}
	close(c.done)
}
