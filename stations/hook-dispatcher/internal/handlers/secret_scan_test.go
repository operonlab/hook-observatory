package handlers

import (
	"strings"
	"testing"
)

func TestSecretScanNonBash(t *testing.T) {
	// Edge: non-Bash tool → always allow
	res := secretScanHandle("PreToolUse", "Write", map[string]any{"command": "git push"}, "")
	if res.IsBlock() {
		t.Errorf("non-Bash tool should allow, got block: %q", res.Reason)
	}
}

func TestSecretScanNoPush(t *testing.T) {
	// Happy path: Bash but not git push → allow
	res := secretScanHandle("PreToolUse", "Bash", map[string]any{"command": "ls -la"}, "")
	if res.IsBlock() {
		t.Errorf("non-push command should allow, got block: %q", res.Reason)
	}
}

func TestSecretScanDryRun(t *testing.T) {
	// Edge: git push --dry-run → allow
	res := secretScanHandle("PreToolUse", "Bash", map[string]any{"command": "git push --dry-run origin main"}, "")
	if res.IsBlock() {
		t.Errorf("dry-run push should allow, got block: %q", res.Reason)
	}
}

func TestSecretScanScanAddedLinesAWSKey(t *testing.T) {
	// AKIA + 16 A-Z/0-9 chars (AWS access key real format)
	diff := "+++ b/config.py\n+aws_key = \"AKIA1234567890ABCDEF\"\n"
	findings := ssScanAddedLines(diff)
	if len(findings) == 0 {
		t.Fatal("expected AWS key finding, got none")
	}
	if !strings.Contains(findings[0], "AWS") {
		t.Errorf("expected AWS in finding, got %q", findings[0])
	}
}

func TestSecretScanScanAddedLinesNosec(t *testing.T) {
	// Lines with # nosec should be skipped
	diff := "+++ b/config.py\n+AKIA1234567890ABCDEF # nosec\n"
	findings := ssScanAddedLines(diff)
	if len(findings) != 0 {
		t.Errorf("nosec line should be skipped, got %v", findings)
	}
}

func TestSecretScanScanAddedLinesFalsePositive(t *testing.T) {
	// Lines with false-positive tokens should be skipped
	diff := "+++ b/README.md\n+# example: api_key = \"your_fake_key_here\"\n"
	findings := ssScanAddedLines(diff)
	if len(findings) != 0 {
		t.Errorf("false-positive line should be skipped, got %v", findings)
	}
}

func TestSecretScanScanAddedLinesTestDir(t *testing.T) {
	// Files in test/ directory should be skipped
	diff := "+++ b/tests/fixtures/config.py\n+AKIA1234567890ABCDEF\n"
	findings := ssScanAddedLines(diff)
	if len(findings) != 0 {
		t.Errorf("test/ file should be skipped, got %v", findings)
	}
}

func TestSecretScanGitHubToken(t *testing.T) {
	diff := "+++ b/deploy.sh\n+GH_TOKEN=ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890\n"
	findings := ssScanAddedLines(diff)
	if len(findings) == 0 {
		t.Error("expected GitHub token finding, got none")
	}
}
