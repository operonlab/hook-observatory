package handlers

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"github.com/joneshong/hook-dispatcher/internal/clients"
	"github.com/joneshong/hook-dispatcher/internal/core"
)

func init() {
	entry := core.Entry{
		Handler:    pmAutopilotHandle,
		ModuleName: "pm_autopilot",
	}
	core.Register("SessionStart", entry)
	core.Register("PostToolUse", core.Entry{
		Matcher:    "Bash",
		Handler:    pmAutopilotHandle,
		ModuleName: "pm_autopilot",
	})
	core.Register("Stop", entry)
}

const (
	pmStateFile     = "/tmp/pm-autopilot-state.json"
	pmMaxSyncIssues = 3
)

var pmIssueRe = regexp.MustCompile(`(?:Closes|Fixes|Refs|Part of)\s+#(\d+)|(?:^|[^\w])#(\d+)\b`)
var pmBranchIssueRe = regexp.MustCompile(`#(\d+)`)

func pmRepo() string {
	// Prefer env var (easy override in tests)
	if r := os.Getenv("PM_AUTOPILOT_REPO"); r != "" {
		return r
	}
	// Read from config YAML directly — github.repo is a top-level key
	// that core.Config doesn't expose, so we read config files ourselves.
	root := os.Getenv("HOOK_OBSERVATORY_ROOT")
	if root == "" {
		home, _ := os.UserHomeDir()
		root = filepath.Join(home, "workshop", "stations", "hook-observatory")
	}
	for _, name := range []string{"config.yaml", "config.example.yaml"} {
		data, err := os.ReadFile(filepath.Join(root, name))
		if err != nil {
			continue
		}
		// Simple extraction: github:\n  repo: "owner/repo"
		lines := strings.Split(string(data), "\n")
		inGithub := false
		for _, line := range lines {
			trimmed := strings.TrimSpace(line)
			if trimmed == "github:" {
				inGithub = true
				continue
			}
			if inGithub {
				if strings.HasPrefix(line, " ") || strings.HasPrefix(line, "\t") {
					if strings.HasPrefix(trimmed, "repo:") {
						val := strings.TrimSpace(strings.TrimPrefix(trimmed, "repo:"))
						val = strings.Trim(val, `"'`)
						if val != "" {
							return val
						}
					}
				} else {
					inGithub = false
				}
			}
		}
	}
	return ""
}

func pmAutopilotHandle(eventType, toolName string, toolInput map[string]any, _ string) core.HookResult {
	repo := pmRepo()
	if repo == "" {
		return core.Allow()
	}
	switch eventType {
	case "SessionStart":
		return pmSessionStart(repo)
	case "PostToolUse":
		if toolName == "Bash" {
			return pmPostBash(toolInput, repo)
		}
	case "Stop":
		return pmOnStop()
	}
	return core.Allow()
}

// ---------------------------------------------------------------------------
// A. SessionStart
// ---------------------------------------------------------------------------

func pmSessionStart(repo string) core.HookResult {
	out, err := clients.RunGH([]string{
		"issue", "list", "--state", "open",
		"--json", "number,title,labels",
		"--limit", "20", "--repo", repo,
	})
	if err != nil {
		pmSaveState(map[string]any{"issues": []any{}, "in_progress": []any{}, "ready": []any{}})
		return core.Allow()
	}

	var issues []map[string]any
	if err := json.Unmarshal([]byte(out), &issues); err != nil || len(issues) == 0 {
		pmSaveState(map[string]any{"issues": []any{}, "in_progress": []any{}, "ready": []any{}})
		return core.Allow()
	}

	var inProgress, blocked, ready []map[string]any
	for _, issue := range issues {
		labels := pmLabelNames(issue)
		switch {
		case pmHasLabel(labels, "in-progress"):
			inProgress = append(inProgress, issue)
		case pmHasLabel(labels, "blocked"):
			blocked = append(blocked, issue)
		default:
			ready = append(ready, issue)
		}
	}

	// Save state
	inProgressNums := pmNumbers(inProgress)
	readyNums := pmNumbers(ready)
	blockedNums := pmNumbers(blocked)
	pmSaveState(map[string]any{
		"issues":      issues,
		"in_progress": inProgressNums,
		"ready":       readyNums,
		"blocked":     blockedNums,
	})

	// Build markdown
	var parts []string
	parts = append(parts, "## GitHub PM Status")

	if len(inProgress) > 0 {
		parts = append(parts, "### In Progress")
		for _, i := range inProgress {
			num, _ := i["number"].(float64)
			title, _ := i["title"].(string)
			labels := pmLabelNames(i)
			var extra []string
			for _, l := range labels {
				if l != "in-progress" {
					extra = append(extra, l)
				}
			}
			suffix := ""
			if len(extra) > 0 {
				suffix = fmt.Sprintf(" (%s)", strings.Join(extra, ", "))
			}
			parts = append(parts, fmt.Sprintf("- #%d %s%s", int(num), title, suffix))
		}
	}

	if len(blocked) > 0 {
		parts = append(parts, "### Blocked")
		for _, i := range blocked {
			num, _ := i["number"].(float64)
			title, _ := i["title"].(string)
			parts = append(parts, fmt.Sprintf("- #%d %s", int(num), title))
		}
	}

	if len(ready) > 0 {
		parts = append(parts, "### Ready")
		limit := ready
		if len(limit) > 5 {
			limit = limit[:5]
		}
		for _, i := range limit {
			num, _ := i["number"].(float64)
			title, _ := i["title"].(string)
			labels := pmLabelNames(i)
			suffix := ""
			if len(labels) > 0 {
				suffix = fmt.Sprintf(" (%s)", strings.Join(labels, ", "))
			}
			parts = append(parts, fmt.Sprintf("- #%d %s%s", int(num), title, suffix))
		}
		if len(ready) > 5 {
			parts = append(parts, fmt.Sprintf("  ... and %d more", len(ready)-5))
		}
	}

	parts = append(parts, fmt.Sprintf(
		"**Total**: %d open (%d in-progress, %d blocked, %d ready)",
		len(issues), len(inProgress), len(blocked), len(ready),
	))

	// Branch context
	branchCtx := pmBranchContext(repo)
	if branchCtx != "" {
		parts = append(parts, "", branchCtx)
	}

	return core.Message(strings.Join(parts, "\n"))
}

func pmBranchContext(repo string) string {
	r := core.RunCmd([]string{"git", "branch", "--show-current"}, "", 3*time.Second, "")
	if r == nil || r.ExitCode != 0 {
		return ""
	}
	branch := strings.TrimSpace(r.Stdout)
	m := pmBranchIssueRe.FindStringSubmatch(branch)
	if m == nil {
		return ""
	}
	issueNum := m[1]

	out, err := clients.RunGH([]string{
		"issue", "view", issueNum, "--repo", repo, "--json", "title,body,state",
	})
	if err != nil {
		return fmt.Sprintf("### Current: #%s\nOn branch `%s`, commits auto-sync to #%s.", issueNum, branch, issueNum)
	}

	var data map[string]any
	if err := json.Unmarshal([]byte(out), &data); err != nil {
		return fmt.Sprintf("### Current: #%s\nOn branch `%s`, commits auto-sync to #%s.", issueNum, branch, issueNum)
	}

	title, _ := data["title"].(string)
	body, _ := data["body"].(string)

	var criteria []string
	for _, line := range strings.Split(body, "\n") {
		if regexp.MustCompile(`^\s*-\s*\[[ xX]\]`).MatchString(line) {
			criteria = append(criteria, strings.TrimSpace(line))
		}
	}

	lines := []string{fmt.Sprintf("### Current: #%s %s", issueNum, title)}
	lines = append(lines, fmt.Sprintf("On branch `%s`, commits auto-sync to #%s.", branch, issueNum))
	if len(criteria) > 0 {
		lines = append(lines, "Acceptance criteria:")
		if len(criteria) > 10 {
			criteria = criteria[:10]
		}
		lines = append(lines, criteria...)
	}
	return strings.Join(lines, "\n")
}

// ---------------------------------------------------------------------------
// B. PostToolUse/Bash
// ---------------------------------------------------------------------------

func pmPostBash(toolInput map[string]any, repo string) core.HookResult {
	command, _ := toolInput["command"].(string)
	if strings.Contains(command, "git commit") {
		return pmHandleCommit(repo)
	}
	if strings.Contains(command, "git merge") {
		return pmHandleMerge(command, repo)
	}
	if strings.Contains(command, "git worktree remove") {
		return pmHandleWorktreeRemove(command, repo)
	}
	return core.Allow()
}

func pmHandleCommit(repo string) core.HookResult {
	logR := core.RunCmd([]string{"git", "log", "-1", "--format=%h%n%s"}, "", 3*time.Second, "")
	if logR == nil || logR.ExitCode != 0 {
		return core.Allow()
	}
	logLines := strings.SplitN(strings.TrimSpace(logR.Stdout), "\n", 2)
	if len(logLines) < 2 {
		return core.Allow()
	}
	commitHash := logLines[0]
	commitSubject := logLines[1]

	fullMsgR := core.RunCmd([]string{"git", "log", "-1", "--format=%s%n%b"}, "", 3*time.Second, "")
	fullMsg := commitSubject
	if fullMsgR != nil {
		fullMsg = strings.TrimSpace(fullMsgR.Stdout)
	}

	branchR := core.RunCmd([]string{"git", "branch", "--show-current"}, "", 3*time.Second, "")
	branch := ""
	if branchR != nil && branchR.ExitCode == 0 {
		branch = strings.TrimSpace(branchR.Stdout)
	}

	issueNums := pmExtractIssues(fullMsg, branch)
	if len(issueNums) == 0 {
		return core.Allow()
	}

	// Cap to MAX_SYNC_ISSUES
	capped := pmSortedCapped(issueNums, pmMaxSyncIssues)

	// Diff stat for comment body
	diffStat := ""
	diffR := core.RunCmd([]string{"git", "diff", "--stat", "HEAD~1..HEAD"}, "", 3*time.Second, "")
	if diffR != nil && diffR.ExitCode == 0 {
		statLines := strings.Split(strings.TrimSpace(diffR.Stdout), "\n")
		if len(statLines) > 0 {
			fileLines := statLines
			summaryLine := ""
			if len(statLines) > 1 {
				fileLines = statLines[:len(statLines)-1]
				summaryLine = statLines[len(statLines)-1]
			}
			if len(fileLines) > 8 {
				extra := len(fileLines) - 8
				fileLines = fileLines[:8]
				diffStat = "\n```\n" + strings.Join(fileLines, "\n") +
					fmt.Sprintf("\n  ... and %d more files", extra)
			} else {
				diffStat = "\n```\n" + strings.Join(fileLines, "\n")
			}
			if summaryLine != "" {
				diffStat += "\n" + summaryLine
			}
			diffStat += "\n```"
		}
	}

	for _, num := range capped {
		body := fmt.Sprintf("Commit `%s`: %s", commitHash, commitSubject)
		if diffStat != "" {
			body += "\n" + diffStat
		}
		clients.RunGHBackground([]string{
			"issue", "comment", num, "--repo", repo, "--body", body,
		})
	}

	labels := make([]string, len(capped))
	for i, n := range capped {
		labels[i] = "#" + n
	}
	extra := ""
	if len(issueNums) > pmMaxSyncIssues {
		extra = fmt.Sprintf(" (+%d skipped)", len(issueNums)-pmMaxSyncIssues)
	}
	return core.Message(fmt.Sprintf("Syncing commit %s to %s%s", commitHash, strings.Join(labels, ", "), extra))
}

func pmHandleMerge(command, repo string) core.HookResult {
	parts := strings.Fields(command)
	branchName := ""
	for i, p := range parts {
		if p == "merge" {
			for j := i + 1; j < len(parts); j++ {
				if !strings.HasPrefix(parts[j], "-") {
					branchName = parts[j]
					break
				}
			}
			break
		}
	}
	if branchName == "" {
		return core.Allow()
	}
	m := pmBranchIssueRe.FindStringSubmatch(branchName)
	if m == nil {
		return core.Allow()
	}
	issueNum := m[1]

	out, err := clients.RunGH([]string{
		"issue", "view", issueNum, "--repo", repo, "--json", "state,title",
	})
	if err != nil {
		return core.Allow()
	}
	var data map[string]any
	if err := json.Unmarshal([]byte(out), &data); err != nil {
		return core.Allow()
	}
	if data["state"] == "OPEN" {
		title, _ := data["title"].(string)
		return core.Message(fmt.Sprintf(
			"Merge detected for #%s (%s). Issue is still OPEN — consider closing it with: `gh issue close %s --repo %s`",
			issueNum, title, issueNum, repo,
		))
	}
	return core.Allow()
}

func pmHandleWorktreeRemove(command, repo string) core.HookResult {
	m := pmBranchIssueRe.FindStringSubmatch(command)
	if m == nil {
		return core.Allow()
	}
	issueNum := m[1]

	out, err := clients.RunGH([]string{
		"issue", "view", issueNum, "--repo", repo, "--json", "state",
	})
	if err != nil {
		return core.Allow()
	}
	var data map[string]any
	if err := json.Unmarshal([]byte(out), &data); err != nil {
		return core.Allow()
	}
	if data["state"] == "OPEN" {
		return core.Message(fmt.Sprintf("Worktree removed but #%s is still OPEN. Forgot to close it?", issueNum))
	}
	return core.Allow()
}

// ---------------------------------------------------------------------------
// C. Stop
// ---------------------------------------------------------------------------

func pmOnStop() core.HookResult {
	state := pmLoadState()
	if state == nil {
		return core.Allow()
	}
	inProgress, _ := state["in_progress"].([]any)
	ready, _ := state["ready"].([]any)
	if len(inProgress) == 0 && len(ready) > 0 {
		issues, _ := state["issues"].([]any)
		issueMap := map[float64]map[string]any{}
		for _, raw := range issues {
			if issue, ok := raw.(map[string]any); ok {
				if num, ok := issue["number"].(float64); ok {
					issueMap[num] = issue
				}
			}
		}
		nextNum, _ := ready[0].(float64)
		if issue, ok := issueMap[nextNum]; ok {
			title, _ := issue["title"].(string)
			return core.Message(fmt.Sprintf("No in-progress issues. Next candidate: #%d %s", int(nextNum), title))
		}
	}
	return core.Allow()
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

func pmExtractIssues(text, branch string) []string {
	seen := map[string]bool{}
	// Closes/Fixes/Refs/Part of #N
	re1 := regexp.MustCompile(`(?:Closes|Fixes|Refs|Part of)\s+#(\d+)`)
	for _, m := range re1.FindAllStringSubmatch(text, -1) {
		seen[m[1]] = true
	}
	// Standalone #N
	re2 := regexp.MustCompile(`(?:^|[^\w])#(\d+)\b`)
	for _, m := range re2.FindAllStringSubmatch(text, -1) {
		seen[m[1]] = true
	}
	// Branch
	if branch != "" {
		if m := pmBranchIssueRe.FindStringSubmatch(branch); m != nil {
			seen[m[1]] = true
		}
	}
	result := make([]string, 0, len(seen))
	for k := range seen {
		result = append(result, k)
	}
	return result
}

func pmSortedCapped(nums []string, max int) []string {
	// Simple insertion sort (small N)
	sorted := make([]string, len(nums))
	copy(sorted, nums)
	for i := 1; i < len(sorted); i++ {
		for j := i; j > 0 && sorted[j] < sorted[j-1]; j-- {
			sorted[j], sorted[j-1] = sorted[j-1], sorted[j]
		}
	}
	if len(sorted) > max {
		return sorted[:max]
	}
	return sorted
}

func pmLabelNames(issue map[string]any) []string {
	labels, _ := issue["labels"].([]any)
	names := make([]string, 0, len(labels))
	for _, l := range labels {
		if lb, ok := l.(map[string]any); ok {
			if name, ok := lb["name"].(string); ok {
				names = append(names, name)
			}
		}
	}
	return names
}

func pmHasLabel(labels []string, target string) bool {
	for _, l := range labels {
		if l == target {
			return true
		}
	}
	return false
}

func pmNumbers(issues []map[string]any) []float64 {
	nums := make([]float64, 0, len(issues))
	for _, i := range issues {
		if n, ok := i["number"].(float64); ok {
			nums = append(nums, n)
		}
	}
	return nums
}

func pmLoadState() map[string]any {
	data, err := os.ReadFile(pmStateFile)
	if err != nil {
		return nil
	}
	var state map[string]any
	if err := json.Unmarshal(data, &state); err != nil {
		return nil
	}
	return state
}

func pmSaveState(data map[string]any) {
	b, err := json.Marshal(data)
	if err != nil {
		return
	}
	_ = os.WriteFile(pmStateFile, b, 0o644)
}
