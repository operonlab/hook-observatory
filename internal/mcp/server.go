// Package mcp wires three stats tools onto a mark3labs/mcp-go server and
// exposes them over stdio.
//
// Tools (1:1 with v0.1.0 Python FastMCP):
//
//	hook_obs_stats   — overview counts (+ optional by_event breakdown)
//	hook_obs_events  — recent events, filtered by event_type/session_id/tool_name
//	hook_obs_tools   — top-N tool usage ranking
//
// All tools return Markdown so the client (Claude Code) can render directly.
package mcp

import (
	"context"
	"fmt"

	mcplib "github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"

	"github.com/joneshong/hook-dispatcher/internal/spool"
	"github.com/joneshong/hook-dispatcher/internal/stats"
)

// NewServer builds an MCPServer with the three hook-observatory tools wired up.
// spoolDir is the directory the tools should read from; pass spool.DefaultSpoolDir()
// for the standard location.
func NewServer(version, spoolDir string) *server.MCPServer {
	s := server.NewMCPServer(
		"hook-observatory",
		version,
		server.WithToolCapabilities(true),
		server.WithLogging(),
	)

	s.AddTool(
		mcplib.NewTool("hook_obs_stats",
			mcplib.WithDescription(
				"Hook event overview: total count, today count, unique sessions, "+
					"optional per-event-type breakdown.",
			),
			mcplib.WithBoolean("include_by_event",
				mcplib.Description("Include per-event-type counts in the output."),
			),
		),
		handleStats(spoolDir),
	)

	s.AddTool(
		mcplib.NewTool("hook_obs_events",
			mcplib.WithDescription(
				"Recent hook events with optional filtering by event_type, session_id, or tool_name.",
			),
			mcplib.WithString("event_type",
				mcplib.Description("Filter by exact event_type (e.g. SessionEnd, PreToolUse)."),
			),
			mcplib.WithString("session_id",
				mcplib.Description("Filter by data.session_id."),
			),
			mcplib.WithString("tool_name",
				mcplib.Description("Filter by data.tool_name."),
			),
			mcplib.WithNumber("limit",
				mcplib.Description("Max rows (1-500, default 20)."),
			),
		),
		handleEvents(spoolDir),
	)

	s.AddTool(
		mcplib.NewTool("hook_obs_tools",
			mcplib.WithDescription(
				"Top-N tool usage ranking based on data.tool_name across all hook events.",
			),
			mcplib.WithNumber("limit",
				mcplib.Description("Max tools to return (1-200, default 20)."),
			),
		),
		handleTools(spoolDir),
	)

	return s
}

// ServeStdio runs the configured server over stdio until stdin closes.
// This is what `hook-dispatcher serve` calls.
func ServeStdio(version, spoolDir string) error {
	return server.ServeStdio(NewServer(version, spoolDir))
}

// ────────────────────────────────────────────────────────────────────────
// Handlers
// ────────────────────────────────────────────────────────────────────────

func handleStats(spoolDir string) server.ToolHandlerFunc {
	return func(ctx context.Context, req mcplib.CallToolRequest) (*mcplib.CallToolResult, error) {
		includeByEvent := req.GetBool("include_by_event", false)
		sum, err := stats.Stats(spoolDir, includeByEvent)
		if err != nil {
			return mcplib.NewToolResultError(fmt.Sprintf("read spool: %v", err)), nil
		}
		return mcplib.NewToolResultText(stats.RenderStats(sum)), nil
	}
}

func handleEvents(spoolDir string) server.ToolHandlerFunc {
	return func(ctx context.Context, req mcplib.CallToolRequest) (*mcplib.CallToolResult, error) {
		filter := stats.EventFilter{
			EventType: req.GetString("event_type", ""),
			SessionID: req.GetString("session_id", ""),
			ToolName:  req.GetString("tool_name", ""),
			Limit:     req.GetInt("limit", 20),
		}
		events, err := stats.Events(spoolDir, filter)
		if err != nil {
			return mcplib.NewToolResultError(fmt.Sprintf("read spool: %v", err)), nil
		}
		return mcplib.NewToolResultText(stats.RenderEvents(events, filter)), nil
	}
}

func handleTools(spoolDir string) server.ToolHandlerFunc {
	return func(ctx context.Context, req mcplib.CallToolRequest) (*mcplib.CallToolResult, error) {
		limit := req.GetInt("limit", 20)
		if limit > 200 {
			limit = 200
		}
		ranks, err := stats.Tools(spoolDir, limit)
		if err != nil {
			return mcplib.NewToolResultError(fmt.Sprintf("read spool: %v", err)), nil
		}
		return mcplib.NewToolResultText(stats.RenderTools(ranks)), nil
	}
}

// 確保 spool 套件被引用（spool.DefaultSpoolDir 被 main.go 用）。
var _ = spool.DefaultSpoolDir
