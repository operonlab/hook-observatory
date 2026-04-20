package handlers

import (
	"strings"
	"testing"
)

type safetyCase struct {
	name     string
	command  string
	wantFrag string // non-empty means we expect a block containing this fragment
}

func TestBashSafety(t *testing.T) {
	cases := []safetyCase{
		// Allow cases
		{"plain ls", "ls -la", ""},
		{"git push no-force", "git push origin main", ""},
		{"git push force-with-lease", "git push --force-with-lease origin feature", ""},
		{"rm non-recursive", "rm file.txt", ""},
		{"rm recursive in subdir", "rm -rf ~/Documents/old-project", ""},

		// Block cases
		{"sudo", "sudo rm file", "privilege escalation"},
		{"chmod 777", "chmod 777 /etc/passwd", "chmod 777"},
		{"git force push", "git push --force origin main", "force push"},
		{"git -f push", "git push -f origin main", "force push"},
		{"git reset hard", "git reset --hard HEAD~5", "reset --hard"},
		{"mkfs", "mkfs.ext4 /dev/sda1", "mkfs"},
		{"fdisk", "fdisk /dev/sda", "fdisk"},
		{"dd zero", "dd if=/dev/zero of=/tmp/x bs=1M", "dd from /dev/zero"},
		{"dd device", "dd if=/tmp/x of=/dev/sda", "dd writing to device"},
		{"docker privileged", "docker run --privileged image", "privileged"},
		{"gh repo delete", "gh repo delete owner/repo", "gh repo delete"},
		{"npm publish", "npm publish --access public", "npm publish"},
		{"yarn publish", "yarn publish", "yarn publish"},
		{"rm rf slash", "rm -rf /", "critical path"},
		{"rm rf star", "rm -rf *", "critical path"},
		{"rm rf home wildcard", "rm -rf ~/*", "critical path"},
		{"rm rf home", "rm -rf ~", "home directory"},
		{"sleep ssh poll", "sleep 60 && ssh host nvidia-smi", "sleep + ssh"},

		// Subshell
		{"subshell sudo", `echo $(sudo whoami)`, "sudo"},
		{"backtick mkfs", "echo `mkfs /dev/sda1`", "mkfs"},

		// Python regex does not distinguish quoted content — kept for parity
		{"quoted sudo still blocks (parity)", `echo "sudo is dangerous"`, "sudo"},
	}

	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			res := bashSafetyHandle(
				"PreToolUse", "Bash",
				map[string]any{"command": c.command}, "",
			)
			if c.wantFrag == "" {
				if res.IsBlock() {
					t.Errorf("expected allow, got block: %q", res.Reason)
				}
				return
			}
			if !res.IsBlock() {
				t.Errorf("expected block containing %q, got allow", c.wantFrag)
				return
			}
			if !strings.Contains(res.Reason, c.wantFrag) {
				t.Errorf("expected reason to contain %q, got %q", c.wantFrag, res.Reason)
			}
		})
	}
}

func TestBashSafetyNonBashTool(t *testing.T) {
	res := bashSafetyHandle("PreToolUse", "Write", map[string]any{"command": "sudo rm"}, "")
	if res.IsBlock() {
		t.Errorf("non-Bash tool should pass through, got block: %q", res.Reason)
	}
}

func TestSplitCommands(t *testing.T) {
	got := splitCommands(`echo "a;b" && ls | grep foo`)
	if len(got) != 3 {
		t.Fatalf("expected 3 segments, got %d: %v", len(got), got)
	}
	if !strings.Contains(got[0], `"a;b"`) {
		t.Errorf("quoted semicolon must be preserved, got %q", got[0])
	}
}
