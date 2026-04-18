package handlers

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"

	"github.com/joneshong/hook-dispatcher/internal/core"
)

func init() {
	core.Register("PreToolUse", core.Entry{
		Matcher:    "Bash",
		Handler:    bashSafetyHandle,
		Critical:   true,
		ModuleName: "bash_safety",
	})
}

// bashSafetyHandle is the Go port of handlers/bash_safety.py.
//
// Layer-2 defense for Bash tool. Blocks destructive / suspicious commands via
// regex on a segment-split command string. Sub-agents also pass through this.
func bashSafetyHandle(_, toolName string, toolInput map[string]any, _ string) core.HookResult {
	if toolName != "Bash" {
		return core.Allow()
	}
	cmd, _ := toolInput["command"].(string)
	if cmd == "" {
		return core.Allow()
	}
	if reason := checkCommand(cmd); reason != "" {
		return core.Block("Safety hook: " + reason)
	}
	return core.Allow()
}

// --- Core checking logic ----------------------------------------------------

var (
	// sleep N [;&|\n]+ ... ssh — anti-pattern for remote polling loops.
	reSleepSSH = regexp.MustCompile(`(?s)\bsleep\s+\S+\s*[;&|\n]+\s*.*\bssh(\s|$)`)

	reSubshellDollar = regexp.MustCompile(`\$\(([^)]+)\)`)
	reSubshellTick   = regexp.MustCompile("`([^`]+)`")

	reRm             = regexp.MustCompile(`\brm\b(.*)`)
	reShortFlagToken = regexp.MustCompile(`(?:^|\s)-([a-zA-Z]+)`)
	reLongFlag       = regexp.MustCompile(`--(\w[\w-]*)`)
	reSudo           = regexp.MustCompile(`\bsudo\b`)
	reMkfs           = regexp.MustCompile(`\bmkfs\b`)
	reFdisk          = regexp.MustCompile(`\bfdisk\b`)
	reDdFrom         = regexp.MustCompile(`\bdd\b.*\bif=/dev/(zero|urandom|random)\b`)
	reDdTo           = regexp.MustCompile(`\bdd\b.*\bof=/dev/`)
	reChmod777       = regexp.MustCompile(`\bchmod\b.*\b777\b`)
	reGitPush        = regexp.MustCompile(`\bgit\s+push\b`)
	reGitForce       = regexp.MustCompile(`--force(\b|$)`)
	reGitForceLease  = regexp.MustCompile(`--force-with-lease\b`)
	reDashF          = regexp.MustCompile(`(?:^|\s)-[a-zA-Z]*f`)
	reGitResetHard   = regexp.MustCompile(`\bgit\s+reset\b.*--hard\b`)
	reGitCleanForce  = regexp.MustCompile(`\bgit\s+clean\b.*-[a-zA-Z]*f`)
	reNpmPublish     = regexp.MustCompile(`\bnpm\s+publish\b`)
	reYarnPublish    = regexp.MustCompile(`\byarn\s+publish\b`)
	reNpmInstall     = regexp.MustCompile(`\bnpm\s+(install|i|add|ci)\b`)
	reYarnInstall    = regexp.MustCompile(`\byarn\s+(install|add)\b`)
	reBareYarn       = regexp.MustCompile(`^\s*yarn\s*$`)
	reDockerPriv     = regexp.MustCompile(`\bdocker\s+run\b.*--privileged\b`)
	reGhRepoDelete   = regexp.MustCompile(`\bgh\s+repo\s+delete\b`)
)

func checkCommand(full string) string {
	if reSleepSSH.MatchString(full) {
		return "sleep + ssh polling — use Fleet dispatch with push callback"
	}

	for _, seg := range splitCommands(full) {
		if r := checkSegment(seg); r != "" {
			return r
		}
	}

	for _, m := range reSubshellDollar.FindAllStringSubmatch(full, -1) {
		for _, seg := range splitCommands(m[1]) {
			if r := checkSegment(seg); r != "" {
				return r + " (in subshell)"
			}
		}
	}

	for _, m := range reSubshellTick.FindAllStringSubmatch(full, -1) {
		for _, seg := range splitCommands(m[1]) {
			if r := checkSegment(seg); r != "" {
				return r + " (in subshell)"
			}
		}
	}

	return ""
}

func checkSegment(cmd string) string {
	cmd = strings.TrimSpace(cmd)
	if cmd == "" {
		return ""
	}

	if m := reRm.FindStringSubmatchIndex(cmd); m != nil {
		if r := checkRm(cmd[m[2]:m[3]]); r != "" {
			return r
		}
	}
	if reSudo.MatchString(cmd) {
		return "sudo (privilege escalation)"
	}
	if reMkfs.MatchString(cmd) {
		return "mkfs (format disk)"
	}
	if reFdisk.MatchString(cmd) {
		return "fdisk (partition disk)"
	}
	if reDdFrom.MatchString(cmd) {
		return "dd from /dev/zero or urandom"
	}
	if reDdTo.MatchString(cmd) {
		return "dd writing to device"
	}
	if reChmod777.MatchString(cmd) {
		return "chmod 777"
	}
	if reGitPush.MatchString(cmd) {
		if (reGitForce.MatchString(cmd) && !reGitForceLease.MatchString(cmd)) || reDashF.MatchString(cmd) {
			return "git force push"
		}
	}
	if reGitResetHard.MatchString(cmd) {
		return "git reset --hard"
	}
	if reGitCleanForce.MatchString(cmd) {
		return "git clean with force"
	}
	if reNpmPublish.MatchString(cmd) {
		return "npm publish"
	}
	if reYarnPublish.MatchString(cmd) {
		return "yarn publish"
	}
	if os.Getenv("PNPM_LOCK_DISABLE") != "1" && hasPnpmLock() {
		if reNpmInstall.MatchString(cmd) {
			return "npm install/add/ci blocked — use pnpm (set PNPM_LOCK_DISABLE=1 to override)"
		}
		if reYarnInstall.MatchString(cmd) {
			return "yarn install/add blocked — use pnpm (set PNPM_LOCK_DISABLE=1 to override)"
		}
		if reBareYarn.MatchString(cmd) {
			return "bare yarn blocked — use pnpm install (set PNPM_LOCK_DISABLE=1 to override)"
		}
	}
	if reDockerPriv.MatchString(cmd) {
		return "docker run --privileged"
	}
	if reGhRepoDelete.MatchString(cmd) {
		return "gh repo delete"
	}
	return ""
}

func checkRm(args string) string {
	shortFlags := ""
	for _, m := range reShortFlagToken.FindAllStringSubmatch(args, -1) {
		if len(m) > 1 {
			shortFlags += m[1]
		}
	}
	longFlags := map[string]bool{}
	for _, m := range reLongFlag.FindAllStringSubmatch(args, -1) {
		if len(m) > 1 {
			longFlags[m[1]] = true
		}
	}
	hasR := strings.ContainsAny(shortFlags, "rR") || longFlags["recursive"]
	hasF := strings.Contains(shortFlags, "f") || longFlags["force"]
	if !(hasR && hasF) {
		return ""
	}

	home, _ := os.UserHomeDir()
	projectRoot := expandUser(core.Cfg().GetPath("project_root"))

	for _, tok := range strings.Fields(args) {
		if strings.HasPrefix(tok, "-") {
			continue
		}
		tok = strings.Trim(tok, `"'`)
		expanded := expandUser(tok)

		switch tok {
		case "/", "*", ".", "..", "/*", "~/*":
			return "rm recursive+force on critical path: " + tok
		}
		if strings.TrimRight(expanded, "/") == home {
			return "rm recursive+force on home directory"
		}
		if projectRoot != "" && strings.TrimRight(expanded, "/") == projectRoot {
			return "rm recursive+force on project root directory"
		}
		if strings.HasPrefix(expanded, home+"/") {
			rel := strings.TrimRight(expanded[len(home)+1:], "/")
			if !strings.Contains(rel, "/") {
				return "rm recursive+force on home-level directory: ~/" + rel
			}
		}
	}
	return ""
}

// splitCommands splits on ;, &&, ||, | while respecting quoted strings.
func splitCommands(cmd string) []string {
	var segments []string
	var cur strings.Builder
	inSingle, inDouble, escaped := false, false, false

	for i := 0; i < len(cmd); i++ {
		c := cmd[i]
		if escaped {
			cur.WriteByte(c)
			escaped = false
			continue
		}
		if c == '\\' {
			escaped = true
			cur.WriteByte(c)
			continue
		}
		if c == '\'' && !inDouble {
			inSingle = !inSingle
			cur.WriteByte(c)
			continue
		}
		if c == '"' && !inSingle {
			inDouble = !inDouble
			cur.WriteByte(c)
			continue
		}
		if !inSingle && !inDouble {
			switch {
			case c == ';':
				segments = append(segments, cur.String())
				cur.Reset()
				continue
			case c == '&' && i+1 < len(cmd) && cmd[i+1] == '&':
				segments = append(segments, cur.String())
				cur.Reset()
				i++
				continue
			case c == '|' && i+1 < len(cmd) && cmd[i+1] == '|':
				segments = append(segments, cur.String())
				cur.Reset()
				i++
				continue
			case c == '|':
				segments = append(segments, cur.String())
				cur.Reset()
				continue
			}
		}
		cur.WriteByte(c)
	}
	if cur.Len() > 0 {
		segments = append(segments, cur.String())
	}
	return segments
}

// --- pnpm-lock caching ------------------------------------------------------

var (
	pnpmOnce sync.Once
	pnpmHas  bool
)

func hasPnpmLock() bool {
	pnpmOnce.Do(func() {
		cwd, err := os.Getwd()
		if err != nil {
			return
		}
		home, _ := os.UserHomeDir()
		for cwd != "/" && cwd != home {
			if _, err := os.Stat(filepath.Join(cwd, "pnpm-lock.yaml")); err == nil {
				pnpmHas = true
				return
			}
			parent := filepath.Dir(cwd)
			if parent == cwd {
				break
			}
			cwd = parent
		}
	})
	return pnpmHas
}

func expandUser(p string) string {
	if !strings.HasPrefix(p, "~") {
		return p
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return p
	}
	if p == "~" {
		return home
	}
	if strings.HasPrefix(p, "~/") {
		return filepath.Join(home, p[2:])
	}
	return p
}
