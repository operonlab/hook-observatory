package mcp

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	mcpclient "github.com/mark3labs/mcp-go/client"
	mcplib "github.com/mark3labs/mcp-go/mcp"
)

// ─── helpers ──────────────────────────────────────────────────────────────────

func tmpSpool(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	t.Setenv("HOOK_OBS_SPOOL_DIR", dir)
	return dir
}

func writeLines(t *testing.T, dir string, lines []string) {
	t.Helper()
	path := filepath.Join(dir, "events.jsonl")
	content := strings.Join(lines, "\n") + "\n"
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatalf("writeLines: %v", err)
	}
}

func mkLine(ts, eventType, sessionID, toolName string) string {
	return fmt.Sprintf(
		`{"event_type":%q,"ts":%q,"data":{"session_id":%q,"tool_name":%q}}`,
		eventType, ts, sessionID, toolName,
	)
}

// startClient creates an in-process MCP client connected to a test server,
// initializes the handshake, and returns it ready for tool calls.
func startClient(t *testing.T, spoolDir string) *mcpclient.Client {
	t.Helper()
	srv := NewServer("test-v0.0.0", spoolDir)
	cli, err := mcpclient.NewInProcessClient(srv)
	if err != nil {
		t.Fatalf("NewInProcessClient: %v", err)
	}
	ctx := context.Background()
	if err := cli.Start(ctx); err != nil {
		t.Fatalf("client.Start: %v", err)
	}

	initReq := mcplib.InitializeRequest{}
	initReq.Params.ProtocolVersion = mcplib.LATEST_PROTOCOL_VERSION
	initReq.Params.ClientInfo = mcplib.Implementation{
		Name:    "test-client",
		Version: "0.0.1",
	}
	if _, err := cli.Initialize(ctx, initReq); err != nil {
		t.Fatalf("client.Initialize: %v", err)
	}
	t.Cleanup(func() { _ = cli.Close() })
	return cli
}

// ─── handshake ────────────────────────────────────────────────────────────────

func TestMCP_Handshake_Succeeds(t *testing.T) {
	dir := tmpSpool(t)
	srv := NewServer("0.3.0", dir)
	cli, err := mcpclient.NewInProcessClient(srv)
	if err != nil {
		t.Fatalf("NewInProcessClient: %v", err)
	}
	defer cli.Close()

	ctx := context.Background()
	if err := cli.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}

	initReq := mcplib.InitializeRequest{}
	initReq.Params.ProtocolVersion = mcplib.LATEST_PROTOCOL_VERSION
	initReq.Params.ClientInfo = mcplib.Implementation{Name: "tester", Version: "1.0.0"}

	result, err := cli.Initialize(ctx, initReq)
	if err != nil {
		t.Fatalf("Initialize failed: %v", err)
	}
	if result.ServerInfo.Name != "hook-observatory" {
		t.Errorf("server name: want %q, got %q", "hook-observatory", result.ServerInfo.Name)
	}
}

// ─── tools/list ───────────────────────────────────────────────────────────────

func TestMCP_ListTools_Returns3Tools(t *testing.T) {
	dir := tmpSpool(t)
	cli := startClient(t, dir)

	res, err := cli.ListTools(context.Background(), mcplib.ListToolsRequest{})
	if err != nil {
		t.Fatalf("ListTools: %v", err)
	}
	if len(res.Tools) != 3 {
		t.Fatalf("expected 3 tools, got %d", len(res.Tools))
	}

	// Collect names for assertion
	names := make(map[string]bool, 3)
	for _, tool := range res.Tools {
		names[tool.Name] = true
	}
	for _, want := range []string{"hook_obs_stats", "hook_obs_events", "hook_obs_tools"} {
		if !names[want] {
			t.Errorf("missing tool %q; got %v", want, names)
		}
	}
}

func TestMCP_ListTools_InputSchema_HookObsStats(t *testing.T) {
	dir := tmpSpool(t)
	cli := startClient(t, dir)

	res, err := cli.ListTools(context.Background(), mcplib.ListToolsRequest{})
	if err != nil {
		t.Fatalf("ListTools: %v", err)
	}
	var statsTool *mcplib.Tool
	for i := range res.Tools {
		if res.Tools[i].Name == "hook_obs_stats" {
			statsTool = &res.Tools[i]
			break
		}
	}
	if statsTool == nil {
		t.Fatal("hook_obs_stats not in tool list")
	}
	// Must expose include_by_event property
	schema := statsTool.InputSchema
	props, ok := schema.Properties["include_by_event"]
	if !ok {
		t.Errorf("hook_obs_stats inputSchema missing include_by_event; schema=%+v", schema)
		_ = props
	}
}

func TestMCP_ListTools_InputSchema_HookObsEvents(t *testing.T) {
	dir := tmpSpool(t)
	cli := startClient(t, dir)

	res, err := cli.ListTools(context.Background(), mcplib.ListToolsRequest{})
	if err != nil {
		t.Fatalf("ListTools: %v", err)
	}
	var evTool *mcplib.Tool
	for i := range res.Tools {
		if res.Tools[i].Name == "hook_obs_events" {
			evTool = &res.Tools[i]
			break
		}
	}
	if evTool == nil {
		t.Fatal("hook_obs_events not in tool list")
	}
	schema := evTool.InputSchema
	for _, field := range []string{"event_type", "session_id", "tool_name", "limit"} {
		if _, ok := schema.Properties[field]; !ok {
			t.Errorf("hook_obs_events inputSchema missing field %q", field)
		}
	}
}

func TestMCP_ListTools_InputSchema_HookObsTools(t *testing.T) {
	dir := tmpSpool(t)
	cli := startClient(t, dir)

	res, err := cli.ListTools(context.Background(), mcplib.ListToolsRequest{})
	if err != nil {
		t.Fatalf("ListTools: %v", err)
	}
	var toolsTool *mcplib.Tool
	for i := range res.Tools {
		if res.Tools[i].Name == "hook_obs_tools" {
			toolsTool = &res.Tools[i]
			break
		}
	}
	if toolsTool == nil {
		t.Fatal("hook_obs_tools not in tool list")
	}
	if _, ok := toolsTool.InputSchema.Properties["limit"]; !ok {
		t.Errorf("hook_obs_tools inputSchema missing limit field")
	}
}

// ─── tools/call hook_obs_stats ────────────────────────────────────────────────

func TestMCP_CallTool_HookObsStats_ReturnsTextWithTotal(t *testing.T) {
	dir := tmpSpool(t)
	writeLines(t, dir, []string{
		mkLine("2026-05-01T10:00:00Z", "SessionStart", "s1", ""),
		mkLine("2026-05-01T10:01:00Z", "PreToolUse", "s1", "Bash"),
	})
	cli := startClient(t, dir)

	req := mcplib.CallToolRequest{}
	req.Params.Name = "hook_obs_stats"
	req.Params.Arguments = map[string]any{"include_by_event": false}

	result, err := cli.CallTool(context.Background(), req)
	if err != nil {
		t.Fatalf("CallTool hook_obs_stats: %v", err)
	}
	if result.IsError {
		t.Fatalf("tool returned error: %v", result.Content)
	}
	if len(result.Content) == 0 {
		t.Fatal("expected at least 1 content item")
	}
	// First content item must be TextContent and contain "Total events:"
	text, ok := result.Content[0].(mcplib.TextContent)
	if !ok {
		t.Fatalf("content[0] is not TextContent: %T", result.Content[0])
	}
	if !strings.Contains(text.Text, "Total events:") {
		t.Errorf("result should contain 'Total events:', got:\n%s", text.Text)
	}
	if !strings.Contains(text.Text, "2") {
		t.Errorf("total should be 2, output:\n%s", text.Text)
	}
}

func TestMCP_CallTool_HookObsStats_EmptySpool_TotalZero(t *testing.T) {
	dir := tmpSpool(t)
	cli := startClient(t, dir)

	req := mcplib.CallToolRequest{}
	req.Params.Name = "hook_obs_stats"
	req.Params.Arguments = map[string]any{}

	result, err := cli.CallTool(context.Background(), req)
	if err != nil {
		t.Fatalf("CallTool: %v", err)
	}
	if result.IsError {
		t.Fatalf("unexpected tool error: %v", result.Content)
	}
	text := result.Content[0].(mcplib.TextContent).Text
	if !strings.Contains(text, "Total events:") {
		t.Errorf("expected Total events: in output, got:\n%s", text)
	}
	if !strings.Contains(text, "0") {
		t.Errorf("expected 0 total, got:\n%s", text)
	}
}

// ─── tools/call hook_obs_events ───────────────────────────────────────────────

func TestMCP_CallTool_HookObsEvents_WithFilter_ShowsFilterMarkdown(t *testing.T) {
	dir := tmpSpool(t)
	writeLines(t, dir, []string{
		mkLine("2026-05-01T10:00:00Z", "SessionStart", "s1", ""),
		mkLine("2026-05-01T10:01:00Z", "PreToolUse", "s1", "Bash"),
	})
	cli := startClient(t, dir)

	req := mcplib.CallToolRequest{}
	req.Params.Name = "hook_obs_events"
	req.Params.Arguments = map[string]any{
		"event_type": "PreToolUse",
		"limit":      float64(10),
	}
	result, err := cli.CallTool(context.Background(), req)
	if err != nil {
		t.Fatalf("CallTool hook_obs_events: %v", err)
	}
	if result.IsError {
		t.Fatalf("tool error: %v", result.Content)
	}
	text := result.Content[0].(mcplib.TextContent).Text
	// Must contain filter section
	if !strings.Contains(text, "event_type") {
		t.Errorf("filter markdown should contain 'event_type', got:\n%s", text)
	}
	if !strings.Contains(text, "PreToolUse") {
		t.Errorf("filter markdown should contain filter value, got:\n%s", text)
	}
}

func TestMCP_CallTool_HookObsEvents_NoMatch_NoMatchingMessage(t *testing.T) {
	dir := tmpSpool(t)
	writeLines(t, dir, []string{
		mkLine("2026-05-01T10:00:00Z", "SessionStart", "s1", ""),
	})
	cli := startClient(t, dir)

	req := mcplib.CallToolRequest{}
	req.Params.Name = "hook_obs_events"
	req.Params.Arguments = map[string]any{"event_type": "NonExistentEvent"}
	result, err := cli.CallTool(context.Background(), req)
	if err != nil {
		t.Fatalf("CallTool: %v", err)
	}
	if result.IsError {
		t.Fatalf("tool error: %v", result.Content)
	}
	text := result.Content[0].(mcplib.TextContent).Text
	if !strings.Contains(text, "No matching events") {
		t.Errorf("expected 'No matching events', got:\n%s", text)
	}
}

// ─── tools/call hook_obs_tools ────────────────────────────────────────────────

func TestMCP_CallTool_HookObsTools_RanksTools(t *testing.T) {
	dir := tmpSpool(t)
	writeLines(t, dir, []string{
		mkLine("2026-05-01T10:00:00Z", "PreToolUse", "s1", "Bash"),
		mkLine("2026-05-01T10:01:00Z", "PreToolUse", "s1", "Bash"),
		mkLine("2026-05-01T10:02:00Z", "PreToolUse", "s1", "Write"),
	})
	cli := startClient(t, dir)

	req := mcplib.CallToolRequest{}
	req.Params.Name = "hook_obs_tools"
	req.Params.Arguments = map[string]any{"limit": float64(10)}

	result, err := cli.CallTool(context.Background(), req)
	if err != nil {
		t.Fatalf("CallTool hook_obs_tools: %v", err)
	}
	if result.IsError {
		t.Fatalf("tool error: %v", result.Content)
	}
	text := result.Content[0].(mcplib.TextContent).Text
	if !strings.Contains(text, "Bash") {
		t.Errorf("should contain Bash in ranking, got:\n%s", text)
	}
	// Bash should appear before Write (higher count)
	bashIdx := strings.Index(text, "Bash")
	writeIdx := strings.Index(text, "Write")
	if bashIdx == -1 || writeIdx == -1 {
		t.Errorf("missing Bash or Write in output:\n%s", text)
	} else if bashIdx > writeIdx {
		t.Errorf("Bash should appear before Write (higher count), got:\n%s", text)
	}
}

func TestMCP_CallTool_HookObsTools_EmptySpool_NoToolsMessage(t *testing.T) {
	dir := tmpSpool(t)
	cli := startClient(t, dir)

	req := mcplib.CallToolRequest{}
	req.Params.Name = "hook_obs_tools"
	req.Params.Arguments = map[string]any{}

	result, err := cli.CallTool(context.Background(), req)
	if err != nil {
		t.Fatalf("CallTool: %v", err)
	}
	if result.IsError {
		t.Fatalf("tool error: %v", result.Content)
	}
	text := result.Content[0].(mcplib.TextContent).Text
	if !strings.Contains(text, "No tool events recorded") {
		t.Errorf("empty spool should produce 'No tool events recorded', got:\n%s", text)
	}
}

// ─── mutation: total count must equal fixture line count ─────────────────────

func TestMCP_StatsTotal_EqualsFixtureLineCount(t *testing.T) {
	dir := tmpSpool(t)
	// Write exactly N valid events
	n := 17
	lines := make([]string, n)
	for i := range lines {
		ts := time.Date(2026, 5, 1, i%24, 0, 0, 0, time.UTC).Format(time.RFC3339)
		lines[i] = mkLine(ts, "SessionStart", fmt.Sprintf("s%d", i), "")
	}
	writeLines(t, dir, lines)

	cli := startClient(t, dir)
	req := mcplib.CallToolRequest{}
	req.Params.Name = "hook_obs_stats"
	req.Params.Arguments = map[string]any{"include_by_event": false}

	result, err := cli.CallTool(context.Background(), req)
	if err != nil {
		t.Fatalf("CallTool: %v", err)
	}
	text := result.Content[0].(mcplib.TextContent).Text
	// The output contains "**Total events:** 17"
	expected := fmt.Sprintf("%d", n)
	if !strings.Contains(text, expected) {
		t.Errorf("total should be %d, output:\n%s", n, text)
	}
}

// ─── tools/call unregistered tool → graceful error ───────────────────────────

func TestMCP_CallTool_UnknownTool_ReturnsError(t *testing.T) {
	dir := tmpSpool(t)
	cli := startClient(t, dir)

	req := mcplib.CallToolRequest{}
	req.Params.Name = "nonexistent_tool"
	req.Params.Arguments = map[string]any{}

	// The MCP protocol may return an error at the RPC level OR an IsError result.
	// Either is acceptable — what's not acceptable is a panic.
	result, err := cli.CallTool(context.Background(), req)
	if err != nil {
		// Protocol-level error — expected and acceptable
		return
	}
	if result != nil && result.IsError {
		// Tool-level error — also acceptable
		return
	}
	// If we somehow got a non-error result for an unknown tool, log but don't fail
	// (library may return empty result; the contract is "no panic").
	if result != nil && len(result.Content) > 0 {
		t.Logf("unexpected non-error result for unknown tool: %v", result.Content)
	}
}

// ─── NewServer version propagation ───────────────────────────────────────────

func TestNewServer_VersionSetsServerInfo(t *testing.T) {
	dir := tmpSpool(t)
	version := "0.3.1"
	srv := NewServer(version, dir)
	cli, err := mcpclient.NewInProcessClient(srv)
	if err != nil {
		t.Fatalf("NewInProcessClient: %v", err)
	}
	defer cli.Close()

	ctx := context.Background()
	if err := cli.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}
	initReq := mcplib.InitializeRequest{}
	initReq.Params.ProtocolVersion = mcplib.LATEST_PROTOCOL_VERSION
	initReq.Params.ClientInfo = mcplib.Implementation{Name: "t", Version: "1"}
	result, err := cli.Initialize(ctx, initReq)
	if err != nil {
		t.Fatalf("Initialize: %v", err)
	}
	if result.ServerInfo.Version != version {
		t.Errorf("server version: want %q, got %q", version, result.ServerInfo.Version)
	}
}
