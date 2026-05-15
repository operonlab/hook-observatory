package stats

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// ─── helpers ──────────────────────────────────────────────────────────────────

func tmpSpool(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	t.Setenv("HOOK_OBS_SPOOL_DIR", dir)
	return dir
}

func writeEvents(t *testing.T, dir string, lines []string) {
	t.Helper()
	path := filepath.Join(dir, "events.jsonl")
	content := strings.Join(lines, "\n") + "\n"
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatalf("writeEvents: %v", err)
	}
}

func mkLine(ts, eventType, sessionID, toolName string) string {
	return fmt.Sprintf(
		`{"event_type":%q,"ts":%q,"data":{"session_id":%q,"tool_name":%q}}`,
		eventType, ts, sessionID, toolName,
	)
}

// todayTS returns an RFC3339 timestamp for today (UTC) at a given hour.
func todayTS(hour int) string {
	now := time.Now().UTC()
	t := time.Date(now.Year(), now.Month(), now.Day(), hour, 0, 0, 0, time.UTC)
	return t.Format(time.RFC3339)
}

// yesterdayTS returns an RFC3339 timestamp for yesterday.
func yesterdayTS(hour int) string {
	now := time.Now().UTC().AddDate(0, 0, -1)
	t := time.Date(now.Year(), now.Month(), now.Day(), hour, 0, 0, 0, time.UTC)
	return t.Format(time.RFC3339)
}

// ═══════════════════════════════════════════════════════════════════
// Stats tests
// ═══════════════════════════════════════════════════════════════════

func TestStats_EmptySpool_TotalZero(t *testing.T) {
	dir := tmpSpool(t)
	// no files at all
	sum, err := Stats(dir, false)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if sum.Total != 0 {
		t.Errorf("want Total=0, got %d", sum.Total)
	}
	if sum.Today != 0 {
		t.Errorf("want Today=0, got %d", sum.Today)
	}
	if sum.UniqueSessions != 0 {
		t.Errorf("want UniqueSessions=0, got %d", sum.UniqueSessions)
	}
}

func TestStats_IncludeByEventFalse_ByEventTypeIsNil(t *testing.T) {
	dir := tmpSpool(t)
	writeEvents(t, dir, []string{
		mkLine("2026-05-01T10:00:00Z", "SessionStart", "s1", ""),
	})
	sum, err := Stats(dir, false)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if sum.ByEventType != nil {
		t.Errorf("ByEventType must be nil when includeByEvent=false, got %v", sum.ByEventType)
	}
}

func TestStats_IncludeByEventTrue_ByEventTypeIsNonNil(t *testing.T) {
	dir := tmpSpool(t)
	writeEvents(t, dir, []string{
		mkLine("2026-05-01T10:00:00Z", "SessionStart", "s1", ""),
		mkLine("2026-05-01T10:01:00Z", "PreToolUse", "s1", "Bash"),
	})
	sum, err := Stats(dir, true)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if sum.ByEventType == nil {
		t.Fatal("ByEventType must be non-nil when includeByEvent=true")
	}
	if sum.ByEventType["SessionStart"] != 1 {
		t.Errorf("expected SessionStart=1, got %d", sum.ByEventType["SessionStart"])
	}
	if sum.ByEventType["PreToolUse"] != 1 {
		t.Errorf("expected PreToolUse=1, got %d", sum.ByEventType["PreToolUse"])
	}
}

func TestStats_TodayFilter_OnlyCountsToday(t *testing.T) {
	dir := tmpSpool(t)
	// 2 today, 1 yesterday
	writeEvents(t, dir, []string{
		mkLine(todayTS(8), "SessionStart", "s1", ""),
		mkLine(todayTS(9), "PreToolUse", "s1", "Bash"),
		mkLine(yesterdayTS(10), "SessionEnd", "s2", ""),
	})
	sum, err := Stats(dir, false)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if sum.Total != 3 {
		t.Errorf("want Total=3, got %d", sum.Total)
	}
	if sum.Today != 2 {
		t.Errorf("want Today=2 (today only), got %d", sum.Today)
	}
}

func TestStats_UniqueSessionCount(t *testing.T) {
	dir := tmpSpool(t)
	writeEvents(t, dir, []string{
		mkLine("2026-05-01T10:00:00Z", "PreToolUse", "sess-A", "Bash"),
		mkLine("2026-05-01T10:01:00Z", "PreToolUse", "sess-A", "Write"), // same session
		mkLine("2026-05-01T10:02:00Z", "PreToolUse", "sess-B", "Read"),
		mkLine("2026-05-01T10:03:00Z", "SessionEnd", "", ""),            // no session_id — excluded
	})
	sum, err := Stats(dir, false)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if sum.UniqueSessions != 2 {
		t.Errorf("want UniqueSessions=2, got %d", sum.UniqueSessions)
	}
}

func TestStats_TotalCountIncludes_AllEvents(t *testing.T) {
	dir := tmpSpool(t)
	n := 37
	lines := make([]string, n)
	for i := range lines {
		lines[i] = mkLine(fmt.Sprintf("2026-05-0%dT10:00:00Z", (i%9)+1), "X", "s", "")
	}
	writeEvents(t, dir, lines)
	sum, err := Stats(dir, false)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if sum.Total != n {
		t.Errorf("want Total=%d, got %d", n, sum.Total)
	}
}

// ═══════════════════════════════════════════════════════════════════
// Events tests
// ═══════════════════════════════════════════════════════════════════

func TestEvents_NoFilter_ReturnsDefaultLimit20(t *testing.T) {
	dir := tmpSpool(t)
	// Write 30 events
	lines := make([]string, 30)
	for i := range lines {
		lines[i] = mkLine(
			fmt.Sprintf("2026-05-01T%02d:00:00Z", i%24),
			"SessionStart", fmt.Sprintf("s%d", i), "",
		)
	}
	writeEvents(t, dir, lines)
	got, err := Events(dir, EventFilter{})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(got) != 20 {
		t.Errorf("default limit should be 20, got %d", len(got))
	}
}

func TestEvents_LimitZero_UsesDefault20(t *testing.T) {
	dir := tmpSpool(t)
	lines := make([]string, 25)
	for i := range lines {
		lines[i] = mkLine(fmt.Sprintf("2026-05-01T%02d:00:00Z", i%24), "E", "s", "")
	}
	writeEvents(t, dir, lines)
	got, err := Events(dir, EventFilter{Limit: 0})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(got) != 20 {
		t.Errorf("limit=0 should default to 20, got %d", len(got))
	}
}

func TestEvents_LimitOver500_ClampedTo500(t *testing.T) {
	dir := tmpSpool(t)
	// Write 600 events
	lines := make([]string, 600)
	for i := range lines {
		lines[i] = mkLine("2026-05-01T10:00:00Z", "X", fmt.Sprintf("s%d", i), "")
	}
	writeEvents(t, dir, lines)
	got, err := Events(dir, EventFilter{Limit: 999})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(got) != 500 {
		t.Errorf("limit>500 should be clamped to 500, got %d", len(got))
	}
}

func TestEvents_FilterEventType_OnlyMatchingReturned(t *testing.T) {
	dir := tmpSpool(t)
	writeEvents(t, dir, []string{
		mkLine("2026-05-01T10:00:00Z", "SessionStart", "s1", ""),
		mkLine("2026-05-01T10:01:00Z", "PreToolUse", "s1", "Bash"),
		mkLine("2026-05-01T10:02:00Z", "PreToolUse", "s1", "Write"),
		mkLine("2026-05-01T10:03:00Z", "PostToolUse", "s1", "Bash"),
	})
	got, err := Events(dir, EventFilter{EventType: "PreToolUse", Limit: 10})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(got) != 2 {
		t.Fatalf("expected 2 PreToolUse events, got %d", len(got))
	}
	for _, ev := range got {
		if ev.EventType != "PreToolUse" {
			t.Errorf("filter leak: got event_type=%q", ev.EventType)
		}
	}
}

func TestEvents_FilterSessionID_AND_ToolName_BothApplied(t *testing.T) {
	dir := tmpSpool(t)
	writeEvents(t, dir, []string{
		mkLine("2026-05-01T10:00:00Z", "PreToolUse", "sessX", "Bash"),   // match both
		mkLine("2026-05-01T10:01:00Z", "PreToolUse", "sessX", "Write"),  // wrong tool
		mkLine("2026-05-01T10:02:00Z", "PreToolUse", "sessY", "Bash"),   // wrong session
		mkLine("2026-05-01T10:03:00Z", "PreToolUse", "sessX", "Bash"),   // match both
	})
	got, err := Events(dir, EventFilter{SessionID: "sessX", ToolName: "Bash", Limit: 10})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(got) != 2 {
		t.Fatalf("expected 2 events matching sessX+Bash, got %d", len(got))
	}
}

func TestEvents_NoMatch_ReturnsEmptySliceNotNilPanic(t *testing.T) {
	dir := tmpSpool(t)
	writeEvents(t, dir, []string{
		mkLine("2026-05-01T10:00:00Z", "SessionStart", "s1", ""),
	})
	got, err := Events(dir, EventFilter{EventType: "NonExistentType", Limit: 10})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	// Must be non-nil empty slice (or nil is also OK — just no panic + length 0)
	if len(got) != 0 {
		t.Errorf("expected 0 results for non-matching filter, got %d", len(got))
	}
}

func TestEvents_NewestFirst(t *testing.T) {
	dir := tmpSpool(t)
	writeEvents(t, dir, []string{
		mkLine("2026-05-01T08:00:00Z", "A", "s1", ""),
		mkLine("2026-05-01T09:00:00Z", "B", "s1", ""),
		mkLine("2026-05-01T10:00:00Z", "C", "s1", ""),
	})
	got, err := Events(dir, EventFilter{Limit: 10})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(got) < 3 {
		t.Fatalf("expected 3 events, got %d", len(got))
	}
	// Newest first → C, B, A
	if got[0].EventType != "C" {
		t.Errorf("first result should be newest (C), got %q", got[0].EventType)
	}
	if got[2].EventType != "A" {
		t.Errorf("last result should be oldest (A), got %q", got[2].EventType)
	}
}

// ═══════════════════════════════════════════════════════════════════
// Tools tests
// ═══════════════════════════════════════════════════════════════════

func TestTools_NoToolName_Excluded(t *testing.T) {
	dir := tmpSpool(t)
	writeEvents(t, dir, []string{
		mkLine("2026-05-01T10:00:00Z", "SessionStart", "s1", ""),  // no tool_name
		mkLine("2026-05-01T10:01:00Z", "PreToolUse", "s1", "Bash"),
	})
	ranks, err := Tools(dir, 20)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(ranks) != 1 {
		t.Fatalf("expected 1 tool ranked, got %d", len(ranks))
	}
	if ranks[0].ToolName != "Bash" {
		t.Errorf("expected Bash, got %q", ranks[0].ToolName)
	}
}

func TestTools_Descending_Order(t *testing.T) {
	dir := tmpSpool(t)
	writeEvents(t, dir, []string{
		mkLine("2026-05-01T10:00:00Z", "PreToolUse", "s1", "Bash"),
		mkLine("2026-05-01T10:01:00Z", "PreToolUse", "s1", "Bash"),
		mkLine("2026-05-01T10:02:00Z", "PreToolUse", "s1", "Bash"),
		mkLine("2026-05-01T10:03:00Z", "PreToolUse", "s1", "Write"),
		mkLine("2026-05-01T10:04:00Z", "PreToolUse", "s1", "Write"),
		mkLine("2026-05-01T10:05:00Z", "PreToolUse", "s1", "Read"),
	})
	ranks, err := Tools(dir, 10)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(ranks) != 3 {
		t.Fatalf("expected 3 tools, got %d", len(ranks))
	}
	// Bash=3 > Write=2 > Read=1
	if ranks[0].ToolName != "Bash" || ranks[0].Count != 3 {
		t.Errorf("rank[0] should be Bash=3, got %q=%d", ranks[0].ToolName, ranks[0].Count)
	}
	if ranks[1].ToolName != "Write" || ranks[1].Count != 2 {
		t.Errorf("rank[1] should be Write=2, got %q=%d", ranks[1].ToolName, ranks[1].Count)
	}
	// Descending invariant
	for i := 1; i < len(ranks); i++ {
		if ranks[i].Count > ranks[i-1].Count {
			t.Errorf("ranks not descending: [%d]=%d > [%d]=%d",
				i, ranks[i].Count, i-1, ranks[i-1].Count)
		}
	}
}

func TestTools_LimitApplied(t *testing.T) {
	dir := tmpSpool(t)
	// 5 distinct tools
	tools := []string{"Bash", "Write", "Read", "Edit", "Glob"}
	lines := make([]string, len(tools))
	for i, tool := range tools {
		lines[i] = mkLine(fmt.Sprintf("2026-05-01T%02d:00:00Z", i), "PreToolUse", "s1", tool)
	}
	writeEvents(t, dir, lines)
	ranks, err := Tools(dir, 3)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(ranks) != 3 {
		t.Errorf("expected limit=3, got %d", len(ranks))
	}
}

func TestTools_EmptySpool_ReturnsEmptyNotNilPanic(t *testing.T) {
	dir := tmpSpool(t)
	ranks, err := Tools(dir, 10)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(ranks) != 0 {
		t.Errorf("expected 0 tools from empty spool, got %d", len(ranks))
	}
}

// ═══════════════════════════════════════════════════════════════════
// Render* tests
// ═══════════════════════════════════════════════════════════════════

func TestRenderStats_ContainsTotalEvents(t *testing.T) {
	s := Summary{Total: 42, Today: 7, UniqueSessions: 3}
	out := RenderStats(s)
	if !strings.Contains(out, "Total events:") {
		t.Errorf("RenderStats must contain 'Total events:', got:\n%s", out)
	}
	if !strings.Contains(out, "42") {
		t.Errorf("RenderStats must contain total count 42, got:\n%s", out)
	}
}

func TestRenderStats_EmptySummary_NoByEventSection(t *testing.T) {
	s := Summary{}
	out := RenderStats(s)
	if out == "" {
		t.Error("RenderStats on empty Summary should return non-empty string")
	}
	// No ByEventType section when map is nil
	if strings.Contains(out, "By event type") {
		t.Errorf("empty ByEventType should not produce 'By event type' section")
	}
}

func TestRenderStats_WithByEventType_IncludesTable(t *testing.T) {
	s := Summary{
		Total:       5,
		ByEventType: map[string]int{"SessionStart": 3, "PreToolUse": 2},
	}
	out := RenderStats(s)
	if !strings.Contains(out, "By event type") {
		t.Errorf("should include 'By event type' header when ByEventType non-empty")
	}
	if !strings.Contains(out, "SessionStart") {
		t.Errorf("should include SessionStart in table")
	}
}

func TestRenderEvents_EmptyEvents_NoMatchingMessage(t *testing.T) {
	out := RenderEvents(nil, EventFilter{})
	if out == "" {
		t.Error("RenderEvents on nil events should return non-empty string")
	}
	if !strings.Contains(out, "No matching events") {
		t.Errorf("empty events should produce 'No matching events', got:\n%s", out)
	}
}

func TestRenderEvents_WithFilter_ShowsFilterSection(t *testing.T) {
	out := RenderEvents(nil, EventFilter{EventType: "PreToolUse"})
	if !strings.Contains(out, "event_type") {
		t.Errorf("filter section should show event_type, got:\n%s", out)
	}
	if !strings.Contains(out, "PreToolUse") {
		t.Errorf("filter section should show filter value, got:\n%s", out)
	}
}

func TestRenderTools_EmptyRanks_NoToolsMessage(t *testing.T) {
	out := RenderTools(nil)
	if out == "" {
		t.Error("RenderTools on nil ranks should return non-empty string")
	}
	if !strings.Contains(out, "No tool events recorded") {
		t.Errorf("empty tools should produce 'No tool events recorded', got:\n%s", out)
	}
}

func TestRenderTools_WithRanks_IncludesTable(t *testing.T) {
	ranks := []ToolRank{
		{ToolName: "Bash", Count: 10},
		{ToolName: "Write", Count: 5},
	}
	out := RenderTools(ranks)
	if !strings.Contains(out, "Bash") {
		t.Errorf("should include Bash in output, got:\n%s", out)
	}
	if !strings.Contains(out, "10") {
		t.Errorf("should include count 10 in output, got:\n%s", out)
	}
}

// ─── Invariant: same input → same output (determinism) ─────────────────────

func TestStats_Deterministic_SameInputSameOutput(t *testing.T) {
	dir := tmpSpool(t)
	writeEvents(t, dir, []string{
		mkLine("2026-05-01T10:00:00Z", "SessionStart", "s1", ""),
		mkLine("2026-05-01T10:01:00Z", "PreToolUse", "s1", "Bash"),
	})
	s1, err1 := Stats(dir, true)
	s2, err2 := Stats(dir, true)
	if err1 != nil || err2 != nil {
		t.Fatalf("errors: %v, %v", err1, err2)
	}
	if s1.Total != s2.Total || s1.Today != s2.Today || s1.UniqueSessions != s2.UniqueSessions {
		t.Errorf("non-deterministic: %+v vs %+v", s1, s2)
	}
}
