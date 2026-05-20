// Package clients provides thin wrappers around external HTTP services
// and CLI tools used by hook handlers.
package clients

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"time"

	portregistry "github.com/joneshong/hook-observatory/internal/portregistry"
)

const liteLLMTimeout = 10 * time.Second

// defaultLiteLLMBase is resolved from the cross-language port registry
// (litellm = 4000) at package init so a yaml-side port change is picked up
// without touching this file.
var defaultLiteLLMBase = portregistry.URL("litellm", "/v1", 4000)

// LiteLLMMessage is one message in the chat completions request.
type LiteLLMMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

// LiteLLMRequest is the POST body for /chat/completions.
type LiteLLMRequest struct {
	Model       string           `json:"model"`
	Messages    []LiteLLMMessage `json:"messages"`
	MaxTokens   int              `json:"max_tokens,omitempty"`
	Temperature float64          `json:"temperature,omitempty"`
}

// LiteLLMComplete sends a single-turn completion request and returns the
// assistant's text.  Returns ("", err) on network or API error — callers
// should treat error as fail-open (return core.Allow()).
func LiteLLMComplete(model string, messages []LiteLLMMessage, maxTokens int, temperature float64) (string, error) {
	base := os.Getenv("LITELLM_API")
	if base == "" {
		base = defaultLiteLLMBase
	}

	body := LiteLLMRequest{
		Model:       model,
		Messages:    messages,
		MaxTokens:   maxTokens,
		Temperature: temperature,
	}

	payload, err := json.Marshal(body)
	if err != nil {
		return "", fmt.Errorf("litellm: marshal: %w", err)
	}

	client := &http.Client{Timeout: liteLLMTimeout}
	resp, err := client.Post(base+"/chat/completions", "application/json", bytes.NewReader(payload))
	if err != nil {
		return "", fmt.Errorf("litellm: post: %w", err)
	}
	defer resp.Body.Close()

	raw, err := io.ReadAll(io.LimitReader(resp.Body, 64*1024))
	if err != nil {
		return "", fmt.Errorf("litellm: read body: %w", err)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return "", fmt.Errorf("litellm: status %d", resp.StatusCode)
	}

	var out struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
	}
	if err := json.Unmarshal(raw, &out); err != nil {
		return "", fmt.Errorf("litellm: unmarshal response: %w", err)
	}
	if len(out.Choices) == 0 {
		return "", fmt.Errorf("litellm: no choices in response")
	}
	return out.Choices[0].Message.Content, nil
}
