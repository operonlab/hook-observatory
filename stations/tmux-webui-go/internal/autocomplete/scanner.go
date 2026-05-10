package autocomplete

import "context"

// Item represents a single autocomplete suggestion.
type Item struct {
	Name        string `json:"name"`
	DisplayName string `json:"display_name,omitempty"`
	Description string `json:"description,omitempty"`
	Type        string `json:"type"` // "skill" | "command" | "agent" | "mcp" | "path"
	Icon        string `json:"icon,omitempty"`
}

// Scanner is the interface implemented by resource scanners (Claude dir, etc.).
// Scan performs the full directory walk and returns all discovered items.
// Implementations must be safe to call concurrently.
type Scanner interface {
	Scan(ctx context.Context) []Item
}
