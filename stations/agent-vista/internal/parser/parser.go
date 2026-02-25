// Package parser defines the TranscriptParser interface.
// FROZEN: Implementations live in cli-specific subpackages (claude/, codex/, gemini/).
package parser

import "github.com/joneshong/agent-vista/internal/protocol"

// TranscriptParser is the common interface for all CLI transcript parsers.
// Each CLI has its own implementation in a subpackage.
type TranscriptParser interface {
	// Detect returns true if the given file path should be handled by this parser.
	Detect(path string) bool

	// ParseIncremental processes newly appended bytes and returns parsed events.
	// For JSONL formats (Claude, Codex): newBytes contains appended lines.
	// For JSON format (Gemini): newBytes contains the full file content for diff comparison.
	ParseIncremental(newBytes []byte) ([]protocol.AgentEvent, error)

	// SessionInfo returns metadata about the current session being parsed.
	SessionInfo() protocol.SessionMeta

	// Reset clears internal state (e.g., when a session restarts or file is replaced).
	Reset()
}
