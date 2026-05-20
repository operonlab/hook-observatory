package clients

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/joneshong/hook-observatory/internal/core"
	portregistry "github.com/joneshong/hook-observatory/internal/portregistry"
)

const memvaultTimeout = 10 * time.Second

// defaultMemvaultBase points at the Workshop core service (port 10000),
// which hosts the /api/memvault/* routes — memvault is a Core module, not
// a standalone station. The previous hardcoded 10205 was a stale port
// (10205 in the registry is `translate`) and every request silently 404'd.
// Resolved from the cross-language port registry so a future move would
// only require a yaml edit.
var defaultMemvaultBase = portregistry.URL("core", "", 10000)

// MemvaultClient is a thin HTTP wrapper around the memvault service.
// Base URL is resolved from config (memvault_url) or the default.
type MemvaultClient struct {
	baseURL string
	http    *http.Client
}

// NewMemvaultClient creates a client using the config-provided or default URL.
func NewMemvaultClient() *MemvaultClient {
	base := core.Cfg().GetService("memvault_url")
	if base == "" {
		base = defaultMemvaultBase
	}
	return &MemvaultClient{
		baseURL: base,
		http:    &http.Client{Timeout: memvaultTimeout},
	}
}

// Extract calls POST /api/memvault/extract.
// Returns the parsed response body map or an error.
func (c *MemvaultClient) Extract(content, blockType string, tags []string) (map[string]any, error) {
	body := map[string]any{
		"content":    content,
		"block_type": blockType,
		"tags":       tags,
	}
	return c.post("/api/memvault/extract", body)
}

// UpdateBlock calls PATCH /api/memvault/blocks/{id}.
func (c *MemvaultClient) UpdateBlock(blockID string, updates map[string]any) (map[string]any, error) {
	payload, err := json.Marshal(updates)
	if err != nil {
		return nil, fmt.Errorf("memvault: marshal: %w", err)
	}
	req, err := http.NewRequest("PATCH", c.baseURL+"/api/memvault/blocks/"+blockID, bytes.NewReader(payload))
	if err != nil {
		return nil, fmt.Errorf("memvault: new request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	return c.do(req)
}

func (c *MemvaultClient) post(path string, body map[string]any) (map[string]any, error) {
	payload, err := json.Marshal(body)
	if err != nil {
		return nil, fmt.Errorf("memvault: marshal: %w", err)
	}
	req, err := http.NewRequest("POST", c.baseURL+path, bytes.NewReader(payload))
	if err != nil {
		return nil, fmt.Errorf("memvault: new request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	return c.do(req)
}

func (c *MemvaultClient) do(req *http.Request) (map[string]any, error) {
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, fmt.Errorf("memvault: http: %w", err)
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 256*1024))
	if err != nil {
		return nil, fmt.Errorf("memvault: read body: %w", err)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("memvault: status %d: %s", resp.StatusCode, string(raw))
	}
	var out map[string]any
	if err := json.Unmarshal(raw, &out); err != nil {
		return nil, fmt.Errorf("memvault: unmarshal: %w", err)
	}
	return out, nil
}
