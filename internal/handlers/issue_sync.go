package handlers

// issue_sync.go — Go port of handlers/issue_sync.py
//
// PostToolUse/Bash: auto-detect issue refs in git commits and sync to GitHub.
//
// When a Bash command contains 'git commit', checks the latest commit for
// issue references (#N, Fixes #N, Closes #N, Part of #N) and posts a
// progress comment on the referenced GitHub Issue.
//
// Matcher: "Bash", deferrable.

import (
	"fmt"
	"regexp"
	"strings"
	"time"

	"github.com/joneshong/hook-observatory/internal/clients"
	"github.com/joneshong/hook-observatory/internal/core"
)

const issueSyncRepo = "JonesHong/workshop"

var (
	// Match: Closes/Fixes/Refs/Part of #N
	reIssueKeyword = regexp.MustCompile(`(?i)(?:Closes|Fixes|Refs|Part of)\s+#(\d+)`)
	// Match standalone #N (not preceded by word char — avoids hex colors like #FF0000)
	reIssueStandalone = regexp.MustCompile(`(?:^|[^\w])#(\d+)\b`)
	// Match #N in branch name
	reIssueBranch = regexp.MustCompile(`#(\d+)`)
)

// NOTE: Not registered. Python handlers/__init__.py does not import or register
// issue_sync — it's inactive in production. Keeping the implementation for
// future opt-in, but no core.Register() call to preserve parity.
func init() {}

func issueSyncHandle(_, _ string, toolInput map[string]any, _ string) core.HookResult {
	command, _ := toolInput["command"].(string)
	if !strings.Contains(command, "git commit") {
		return core.Allow()
	}

	// Get latest commit hash + subject
	gitLog := core.RunCmd([]string{"git", "log", "-1", "--format=%h%n%s"}, "", 5*time.Second, "")
	if gitLog == nil || gitLog.ExitCode != 0 {
		return core.Allow()
	}
	parts := strings.SplitN(strings.TrimSpace(gitLog.Stdout), "\n", 2)
	if len(parts) < 2 {
		return core.Allow()
	}
	commitHash := parts[0]
	commitSubject := parts[1]

	// Get full message (subject + body)
	fullMsgOut := core.RunCmd([]string{"git", "log", "-1", "--format=%s%n%b"}, "", 5*time.Second, "")
	fullMsg := commitSubject
	if fullMsgOut != nil && fullMsgOut.ExitCode == 0 {
		fullMsg = strings.TrimSpace(fullMsgOut.Stdout)
	}

	// Collect issue numbers
	issueNumbers := make(map[string]struct{})

	for _, m := range reIssueKeyword.FindAllStringSubmatch(fullMsg, -1) {
		issueNumbers[m[1]] = struct{}{}
	}
	for _, m := range reIssueStandalone.FindAllStringSubmatch(fullMsg, -1) {
		issueNumbers[m[1]] = struct{}{}
	}

	// Check branch name
	branchOut := core.RunCmd([]string{"git", "branch", "--show-current"}, "", 5*time.Second, "")
	if branchOut != nil && branchOut.ExitCode == 0 {
		branch := strings.TrimSpace(branchOut.Stdout)
		if m := reIssueBranch.FindStringSubmatch(branch); m != nil {
			issueNumbers[m[1]] = struct{}{}
		}
	}

	if len(issueNumbers) == 0 {
		return core.Allow()
	}

	// Post comment on each referenced issue (fire-and-forget)
	var synced []string
	comment := fmt.Sprintf("Commit `%s`: %s", commitHash, commitSubject)
	for num := range issueNumbers {
		_, err := clients.RunGH([]string{
			"issue", "comment", num,
			"--repo", issueSyncRepo,
			"--body", comment,
		})
		if err == nil {
			synced = append(synced, "#"+num)
		}
	}

	if len(synced) > 0 {
		return core.Message(fmt.Sprintf("Synced commit %s to %s", commitHash, strings.Join(synced, ", ")))
	}
	return core.Allow()
}
