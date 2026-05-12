package handlers

import (
	"os"
	"regexp"
	"strings"
	"time"

	"github.com/joneshong/hook-dispatcher/internal/core"
)

func init() {
	core.Register("PreToolUse", core.Entry{
		Matcher:    "Bash",
		Handler:    secretScanHandle,
		Critical:   true,
		ModuleName: "secret_scan",
	})
}

// secretScanHandle is the Go port of handlers/secret_scan.py.
//
// Scans the unpushed git diff for hardcoded secrets before a `git push`.
// Escape hatches: SECRET_SCAN_DISABLE=1 env var, or `# nosec` / `// nosec` line suffix.
// On timeout or diff-fetch failure, warns (message) rather than blocking.
func secretScanHandle(_, toolName string, toolInput map[string]any, _ string) core.HookResult {
	if toolName != "Bash" {
		return core.Allow()
	}
	if os.Getenv("SECRET_SCAN_DISABLE") == "1" {
		return core.Allow()
	}

	command, _ := toolInput["command"].(string)
	if command == "" {
		return core.Allow()
	}

	// Only fire on `git push` (not --dry-run)
	if !reGitPushCmd.MatchString(command) {
		return core.Allow()
	}
	if strings.Contains(command, "--dry-run") {
		return core.Allow()
	}

	diffText, ok := ssGetUnpushedDiff()
	if !ok {
		return core.Message("⚠️ secret scan: 無法取得 diff，掃描跳過")
	}
	if strings.TrimSpace(diffText) == "" {
		return core.Allow()
	}

	findings := ssScanAddedLines(diffText)
	if len(findings) == 0 {
		return core.Allow()
	}

	var sb strings.Builder
	limit := len(findings)
	if limit > 5 {
		limit = 5
	}
	for _, f := range findings[:limit] {
		sb.WriteString("  - ")
		sb.WriteString(f)
		sb.WriteByte('\n')
	}
	if len(findings) > 5 {
		sb.WriteString("  ... and ")
		sb.WriteString(itoa(len(findings) - 5))
		sb.WriteString(" more\n")
	}

	return core.Block(
		"偵測到疑似 secret (" + itoa(len(findings)) + " 處):\n" +
			sb.String() +
			"若為誤報，在行尾加 # nosec 或設 SECRET_SCAN_DISABLE=1",
	)
}

// ---------------------------------------------------------------------------
// Secret patterns — mirrors Python _PATTERNS exactly
// ---------------------------------------------------------------------------

type ssPattern struct {
	re    *regexp.Regexp
	label string
}

var ssPatterns = []ssPattern{
	{regexp.MustCompile(`AKIA[0-9A-Z]{16}`), "AWS Access Key"},
	{regexp.MustCompile(`gh[ps]_[A-Za-z0-9_]{36,}`), "GitHub Token"},
	{regexp.MustCompile(`xox[baprs]-[A-Za-z0-9-]{10,}`), "Slack Token"},
	{regexp.MustCompile(`-----BEGIN .* PRIVATE KEY-----`), "Private Key"}, // nosec
	// Generic secret assignment — case-insensitive
	{regexp.MustCompile(`(?i)(?:api[_-]?key|secret[_-]?key|access[_-]?token|password)\s*[=:]\s*['"][^'"]{12,}`), "Generic Secret Assignment"},
}

// False-positive tokens — lines containing any of these are skipped
var ssFalsePositiveTokens = []string{
	"example", "placeholder", "changeme", "todo", "fixme",
	"your-", "your_", "xxx", "dummy", "fake", "mock", "test_", "sample", "template",
}

// File path substrings that mean "skip this file"
var ssSkipPathPatterns = []string{
	"test/", "tests/", "fixtures/", "mocks/",
	"_archive/", "/archive/",
	".example", ".sample", ".template",
}

// Comment prefixes that mean "skip this line"
var ssCommentPrefixes = []string{"#", "//", "/*", "*", "<!--"}

var reGitPushCmd = regexp.MustCompile(`\bgit\s+push\b`)

// ---------------------------------------------------------------------------
// Diff fetching
// ---------------------------------------------------------------------------

// ssGetUnpushedDiff returns (diffText, true) or ("", false) on failure.
func ssGetUnpushedDiff() (string, bool) {
	attempts := [][]string{
		{"git", "diff", "@{upstream}..HEAD"},
		{"git", "diff", "origin/main..HEAD"},
		{"git", "log", "-1", "-p", "--format="},
	}
	for _, args := range attempts {
		res := core.RunCmd(args, "", 3*time.Second, "")
		if res != nil && res.ExitCode == 0 {
			return res.Stdout, true
		}
	}
	return "", false
}

// ---------------------------------------------------------------------------
// Line scanning
// ---------------------------------------------------------------------------

func ssScanAddedLines(diffText string) []string {
	var findings []string
	currentFile := ""

	for _, rawLine := range strings.Split(diffText, "\n") {
		// Track current file
		if strings.HasPrefix(rawLine, "+++ b/") {
			currentFile = rawLine[6:]
			continue
		}
		// Only added lines (not the +++ header itself)
		if !strings.HasPrefix(rawLine, "+") || strings.HasPrefix(rawLine, "+++") {
			continue
		}
		addedLine := rawLine[1:] // strip leading +

		// Skip files in skip-path patterns
		if ssMatchesSkipPath(currentFile) {
			continue
		}

		stripped := strings.TrimSpace(addedLine)

		// Skip comment lines
		if ssIsComment(stripped) {
			continue
		}

		// Skip nosec annotations
		if strings.Contains(addedLine, "# nosec") || strings.Contains(addedLine, "// nosec") {
			continue
		}

		// Skip false-positive tokens
		lower := strings.ToLower(addedLine)
		if ssHasFalsePositive(lower) {
			continue
		}

		// Check patterns
		for _, p := range ssPatterns {
			if p.re.MatchString(addedLine) {
				preview := strings.TrimSpace(addedLine)
				if len(preview) > 40 {
					preview = preview[:40] + "..."
				}
				findings = append(findings, p.label+" in "+currentFile+": "+preview)
				break // one finding per line
			}
		}
	}
	return findings
}

func ssMatchesSkipPath(file string) bool {
	for _, pat := range ssSkipPathPatterns {
		if strings.Contains(file, pat) {
			return true
		}
	}
	return false
}

func ssIsComment(stripped string) bool {
	for _, pfx := range ssCommentPrefixes {
		if strings.HasPrefix(stripped, pfx) {
			return true
		}
	}
	return false
}

func ssHasFalsePositive(lower string) bool {
	for _, tok := range ssFalsePositiveTokens {
		if strings.Contains(lower, tok) {
			return true
		}
	}
	return false
}

// ---------------------------------------------------------------------------
// Tiny helpers
// ---------------------------------------------------------------------------

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	buf := [20]byte{}
	pos := len(buf)
	neg := n < 0
	if neg {
		n = -n
	}
	for n > 0 {
		pos--
		buf[pos] = byte('0' + n%10)
		n /= 10
	}
	if neg {
		pos--
		buf[pos] = '-'
	}
	return string(buf[pos:])
}
