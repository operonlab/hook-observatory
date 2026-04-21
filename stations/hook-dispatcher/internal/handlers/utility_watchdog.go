package handlers

// utility_watchdog.go — Go port of handlers/utility_watchdog.py
//
// SessionEnd: Go in-process port — calls Anvil HTTP API, computes dynamic
//             threshold, appends proposals to JSONL. No Python subprocess.
// SessionStart: read proposals.jsonl + create-proposals.jsonl and emit a
//
//	reminder message if enough proposals have accumulated.

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/joneshong/hook-dispatcher/internal/core"
)

const (
	uwProposalThreshold = 3       // min proposals per skill before alerting
	uwCreateThreshold   = 5       // min create-proposal lines before alerting
	uwMaxFileSize       = 100_000 // bytes — truncate beyond this

	// Anvil HTTP API
	uwAnvilBase       = "http://127.0.0.1:10301"
	uwThresholdBase   = 0.7
	uwThresholdFactor = 0.02
	uwMinInvocations  = 5
)

func init() {
	entry := core.Entry{
		Matcher:    "",
		Handler:    utilityWatchdogHandle,
		Critical:   false,
		ModuleName: "utility_watchdog",
	}
	core.Register("SessionEnd", entry)
	core.Register("SessionStart", entry)
}

func utilityWatchdogHandle(eventType, _ string, _ map[string]any, rawInput string) core.HookResult {
	switch eventType {
	case "SessionEnd":
		return uwHandleSessionEnd(rawInput)
	case "SessionStart":
		return uwHandleSessionStart()
	default:
		return core.Allow()
	}
}

// ---------------------------------------------------------------------------
// SessionEnd: Go in-process utility check (replaces utility_check.py subprocess)
// ---------------------------------------------------------------------------

func uwHandleSessionEnd(rawInput string) core.HookResult {
	var data map[string]any
	if rawInput != "" {
		if err := json.Unmarshal([]byte(rawInput), &data); err != nil {
			return core.Allow()
		}
	}

	sessionID, _ := data["session_id"].(string)
	if sessionID == "" {
		return core.Allow()
	}

	dataDir := uwDataDir()
	if err := os.MkdirAll(dataDir, 0o755); err != nil {
		return core.Allow()
	}

	// Run in background goroutine — same semantics as RunBackground
	go uwCheckInProc(sessionID, dataDir)
	return core.Allow()
}

// uwCheckInProc is the Go in-process port of utility_check.py main().
// Calls Anvil API (HTTP), computes dynamic threshold, appends proposals to JSONL.
func uwCheckInProc(sessionID, dataDir string) {
	client := &http.Client{Timeout: 15 * time.Second}

	// 1. List invocations for this session
	invData, err := uwAnvilGet(client, "/api/anvil/invocations", map[string]string{
		"session_id": sessionID,
		"limit":      "500",
	})
	if err != nil {
		fmt.Fprintf(os.Stderr, "[utility-watchdog] Cannot reach Anvil: %v\n", err)
		return
	}

	items, _ := invData["items"].([]any)

	// Collect skill names from session
	sessionSkills := map[string]bool{}
	for _, raw := range items {
		item, ok := raw.(map[string]any)
		if !ok {
			continue
		}
		if cat, _ := item["category"].(string); cat == "skill" {
			if name, _ := item["skill_name"].(string); name != "" {
				sessionSkills[name] = true
			}
		}
	}

	// CreateOnMiss: no skills but real work done
	if len(sessionSkills) == 0 {
		uwCheckCreateOnMiss(sessionID, len(items), dataDir)
		return
	}

	// 2. Check utility for each skill
	now := time.Now().UTC().Format(time.RFC3339)
	var proposals []map[string]any

	for skillName := range sessionSkills {
		utilData, err := uwAnvilGet(client, "/api/anvil/stats/"+skillName+"/utility", map[string]string{
			"window_days": "90",
		})
		if err != nil {
			continue
		}

		nTotal := uwInt(utilData["total_invocations"])
		utilityScore, hasUtility := utilData["utility_score"]

		if nTotal < uwMinInvocations || !hasUtility || utilityScore == nil {
			continue
		}

		utility := uwFloat(utilityScore)
		threshold := uwDynamicThreshold(nTotal)

		if utility < threshold {
			proposals = append(proposals, map[string]any{
				"skill_name": skillName,
				"utility":    math.Round(utility*10000) / 10000,
				"threshold":  math.Round(threshold*10000) / 10000,
				"n_total":    nTotal,
				"session_id": sessionID,
				"ts":         now,
			})
		}
	}

	// 2b. Trigger attribution for sessions with multi-skill failures
	var failedSkills []string
	for skillName := range sessionSkills {
		if uwHasFailures(client, skillName, sessionID) {
			failedSkills = append(failedSkills, skillName)
		}
	}
	if len(failedSkills) >= 2 {
		// best-effort POST
		_, _ = uwAnvilPost(client, "/api/anvil/invocations/attribute/"+sessionID, nil)
	}

	// 3. Append proposals to JSONL
	if len(proposals) == 0 {
		return
	}

	proposalsFile := filepath.Join(dataDir, "proposals.jsonl")
	f, err := os.OpenFile(proposalsFile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	defer f.Close()
	for _, p := range proposals {
		b, _ := json.Marshal(p)
		fmt.Fprintf(f, "%s\n", b)
	}
	fmt.Fprintf(os.Stderr, "[utility-watchdog] %d proposals for session %s\n", len(proposals), sessionID[:8])
}

// ---------------------------------------------------------------------------
// Helpers for Anvil HTTP API
// ---------------------------------------------------------------------------

func uwAnvilGet(client *http.Client, path string, params map[string]string) (map[string]any, error) {
	u, _ := url.Parse(uwAnvilBase + path)
	q := u.Query()
	for k, v := range params {
		q.Set(k, v)
	}
	u.RawQuery = q.Encode()

	resp, err := client.Get(u.String())
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	var out map[string]any
	if err := json.Unmarshal(body, &out); err != nil {
		return nil, fmt.Errorf("decode: %w", err)
	}
	return out, nil
}

func uwAnvilPost(client *http.Client, path string, payload map[string]any) (map[string]any, error) {
	bodyBytes, _ := json.Marshal(payload)
	resp, err := client.Post(uwAnvilBase+path, "application/json", bytes.NewReader(bodyBytes))
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	var out map[string]any
	_ = json.Unmarshal(body, &out)
	return out, nil
}

func uwHasFailures(client *http.Client, skillName, sessionID string) bool {
	data, err := uwAnvilGet(client, "/api/anvil/invocations", map[string]string{
		"skill_name": skillName,
		"session_id": sessionID,
		"limit":      "500",
	})
	if err != nil {
		return false
	}
	items, _ := data["items"].([]any)
	for _, raw := range items {
		item, ok := raw.(map[string]any)
		if !ok {
			continue
		}
		if success, _ := item["success"].(bool); !success {
			// success field missing or false
			if _, has := item["success"]; has {
				return true
			}
		}
	}
	return false
}

// uwCheckCreateOnMiss detects sessions with no skill usage but real work done.
func uwCheckCreateOnMiss(sessionID string, toolCount int, dataDir string) {
	if toolCount < 3 {
		return
	}
	createFile := filepath.Join(dataDir, "create-proposals.jsonl")
	f, err := os.OpenFile(createFile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	defer f.Close()
	entry := map[string]any{
		"session_id": sessionID,
		"tool_count": toolCount,
		"ts":         time.Now().UTC().Format(time.RFC3339),
	}
	b, _ := json.Marshal(entry)
	fmt.Fprintf(f, "%s\n", b)
	fmt.Fprintf(os.Stderr, "[utility-watchdog] CreateOnMiss for session %s\n", sessionID[:8])
}

// uwDynamicThreshold mirrors Python dynamic_threshold: base + factor * ln(n_total).
func uwDynamicThreshold(nTotal int) float64 {
	if nTotal <= 1 {
		return uwThresholdBase
	}
	return uwThresholdBase + uwThresholdFactor*math.Log(float64(nTotal))
}

func uwFloat(v any) float64 {
	switch x := v.(type) {
	case float64:
		return x
	case float32:
		return float64(x)
	case int:
		return float64(x)
	case json.Number:
		f, _ := x.Float64()
		return f
	}
	return 0
}

func uwInt(v any) int {
	switch x := v.(type) {
	case float64:
		return int(x)
	case int:
		return x
	case json.Number:
		i, _ := x.Int64()
		return int(i)
	}
	return 0
}

// ---------------------------------------------------------------------------
// SessionStart: inject reminder if proposals have accumulated
// ---------------------------------------------------------------------------

func uwHandleSessionStart() core.HookResult {
	dataDir := uwDataDir()
	proposalsFile := filepath.Join(dataDir, "proposals.jsonl")
	createFile := filepath.Join(dataDir, "create-proposals.jsonl")

	var messages []string

	// 1. Utility proposals
	if info, err := os.Stat(proposalsFile); err == nil {
		if info.Size() > uwMaxFileSize {
			_ = os.WriteFile(proposalsFile, []byte(""), 0o644)
			return core.Allow()
		}

		raw, err := os.ReadFile(proposalsFile)
		if err == nil {
			skillCounts := map[string][]map[string]any{}
			for _, line := range strings.Split(string(raw), "\n") {
				line = strings.TrimSpace(line)
				if line == "" {
					continue
				}
				var entry map[string]any
				if err := json.Unmarshal([]byte(line), &entry); err != nil {
					continue
				}
				name, _ := entry["skill_name"].(string)
				if name != "" {
					skillCounts[name] = append(skillCounts[name], entry)
				}
			}

			flagged := map[string]any{}
			for name, entries := range skillCounts {
				if len(entries) >= uwProposalThreshold {
					latest := entries[len(entries)-1]
					flagged[name] = latest["utility"]
				}
			}

			if len(flagged) > 0 {
				parts := make([]string, 0, len(flagged))
				for name, score := range flagged {
					scoreStr := "?"
					if score != nil {
						b, _ := json.Marshal(score)
						scoreStr = strings.Trim(string(b), `"`)
					}
					parts = append(parts, name+"("+scoreStr+")")
				}
				messages = append(messages,
					"[Utility Watchdog] "+itoa(len(flagged))+" skills below threshold: "+
						strings.Join(parts, ", ")+". Consider /skill-optimizer.",
				)

				// Clean up: remove alerted skills
				var remaining []string
				for name, entries := range skillCounts {
					if _, wasFlagged := flagged[name]; !wasFlagged {
						for _, e := range entries {
							b, _ := json.Marshal(e)
							remaining = append(remaining, string(b))
						}
					}
				}
				newContent := ""
				if len(remaining) > 0 {
					newContent = strings.Join(remaining, "\n") + "\n"
				}
				_ = os.WriteFile(proposalsFile, []byte(newContent), 0o644)
			}
		}
	}

	// 2. CreateOnMiss proposals
	if info, err := os.Stat(createFile); err == nil {
		if info.Size() > uwMaxFileSize {
			_ = os.WriteFile(createFile, []byte(""), 0o644)
			return core.Allow()
		}

		raw, err := os.ReadFile(createFile)
		if err == nil {
			var createLines []string
			for _, line := range strings.Split(string(raw), "\n") {
				if strings.TrimSpace(line) != "" {
					createLines = append(createLines, line)
				}
			}
			if len(createLines) >= uwCreateThreshold {
				messages = append(messages,
					"[CreateOnMiss] "+itoa(len(createLines))+" sessions completed without skills. Consider /create-skill.",
				)
				_ = os.WriteFile(createFile, []byte(""), 0o644)
			}
		}
	}

	if len(messages) > 0 {
		return core.Message(strings.Join(messages, " | "))
	}
	return core.Allow()
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func uwDataDir() string {
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".claude", "data", "utility-watchdog")
}

// Note: itoa() is defined in secret_scan.go (same package).
