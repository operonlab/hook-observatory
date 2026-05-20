package handlers

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/joneshong/hook-observatory/internal/core"
)

func init() {
	core.Register("PreToolUse", core.Entry{
		Matcher:    "Write|Edit",
		Handler:    skillSecurityHandle,
		Critical:   true,
		ModuleName: "skill_security",
	})
}

// skillSecurityHandle is the Go port of handlers/skill_security.py.
//
// Scans SKILL.md content for S1 (prompt injection), S2 (privilege escalation),
// S3 (data exfiltration) threats before writing/editing skill files.
func skillSecurityHandle(_, toolName string, toolInput map[string]any, _ string) core.HookResult {
	if toolName != "Write" && toolName != "Edit" {
		return core.Allow()
	}

	filePath, _ := toolInput["file_path"].(string)
	if !ssecIsSkillMarkdown(filePath) {
		return core.Allow()
	}

	var content string
	if toolName == "Write" {
		content, _ = toolInput["content"].(string)
	} else {
		content, _ = toolInput["new_string"].(string)
	}
	if content == "" {
		return core.Allow()
	}

	findings := ssecScanContent(content)
	var critical []ssecFinding
	for _, f := range findings {
		cat := f.category
		if cat == "S1" || cat == "S2" || cat == "S3" {
			critical = append(critical, f)
		}
	}
	if len(critical) == 0 {
		return core.Allow()
	}

	limit := len(critical)
	if limit > 5 {
		limit = 5
	}
	var sb strings.Builder
	for _, f := range critical[:limit] {
		sb.WriteString("  Line ")
		sb.WriteString(itoa(f.lineNum))
		sb.WriteString(": ")
		sb.WriteString(f.description)
		sb.WriteByte('\n')
	}

	dirName := filepath.Base(filepath.Dir(filePath))
	return core.Block(
		"Security Gate: " + itoa(len(critical)) + " critical finding(s) in skill file " +
			dirName + "/\n" + sb.String() +
			"Run /skill-security-scan for deep analysis.",
	)
}

// ---------------------------------------------------------------------------
// Pattern tables — mirrors Python _S1, _S2, _S3 exactly
// ---------------------------------------------------------------------------

type ssecPatEntry struct {
	re          *regexp.Regexp
	description string
}

// S1: Prompt injection
var ssecS1 = []ssecPatEntry{
	{regexp.MustCompile(`(?i)ignore\s+(all\s+)?previous\s+instructions`), "S1: prompt override — 'ignore previous instructions'"},
	{regexp.MustCompile(`(?i)you\s+are\s+now\s+a`), "S1: identity hijack — 'you are now a'"},
	{regexp.MustCompile(`(?i)system\s*prompt\s*override`), "S1: explicit system prompt override"},
	{regexp.MustCompile(`(?i)(?:forget|disregard)\s+(?:everything|all|your|the)`), "S1: memory wipe — 'forget everything'"},
	{regexp.MustCompile(`(?i)new\s+instructions?\s*:`), "S1: instruction injection — 'new instructions:'"},
	{regexp.MustCompile(`(?i)<\s*/?system\s*>`), "S1: XML system tag injection"},
	{regexp.MustCompile(`]\s*}\s*}\s*{`), "S1: JSON structure escape attempt"},
	{regexp.MustCompile(`(?i)(?:^|\n)\s*---\s*\n.*?role\s*:\s*system`), "S1: YAML frontmatter role injection"},
}

// S2: Privilege escalation
var ssecS2 = []ssecPatEntry{
	{regexp.MustCompile(`\bdangerouslyDisableSandbox\b`), "S2: sandbox disable request"},
	{regexp.MustCompile(`\bsudo\s+`), "S2: sudo in skill content"},
	{regexp.MustCompile(`\bchmod\s+777\b`), "S2: world-writable permission"},
	{regexp.MustCompile(`--no-verify\b`), "S2: git hook bypass"},
	{regexp.MustCompile(`\.claude/settings\.json`), "S2: attempt to modify Claude settings"},
	{regexp.MustCompile(`\.claude/hooks/`), "S2: attempt to modify hooks directory"},
	{regexp.MustCompile(`\.claude/rules/`), "S2: attempt to modify rules directory"},
	{regexp.MustCompile(`(?i)\bkill\s+.*claude`), "S2: kill Claude process"},
	{regexp.MustCompile(`(?i)\bpkill\s+.*claude`), "S2: pkill Claude process"},
	{regexp.MustCompile(`\bgit\s+push\s+--force\b`), "S2: force push in skill"},
	{regexp.MustCompile(`\bgit\s+reset\s+--hard\b`), "S2: hard reset in skill"},
}

// S3: Data exfiltration
// Note: Python uses negative lookaheads for curl/wget; Go RE2 doesn't support lookaheads.
// We implement the "curl not to localhost" check in two steps (matched separately).
var ssecS3 = []ssecPatEntry{
	// curl / wget handled specially — see ssecCheckCurlWget
	{regexp.MustCompile(`\.env\b`), "S3: .env file access (not .env.d.ts)"},
	{regexp.MustCompile(`\.ssh/`), "S3: SSH directory access"},
	{regexp.MustCompile(`\.aws/`), "S3: AWS credentials access"},
	// credentials not followed by .md / documentation / example
	{regexp.MustCompile(`(?i)\bcredentials\b`), "S3: credentials file access"},
	{regexp.MustCompile(`(?i)(?:api[_-]?key|secret[_-]?key|access[_-]?token)\s*[=:]\s*['"][^'"]{8,}`), "S3: hardcoded secret"},
	{regexp.MustCompile(`(?i)base64\s*(?:encode|decode).*(?:curl|wget|http)`), "S3: base64 + HTTP exfil pattern"},
}

// Allowlist patterns — lines matching any of these are skipped (mirrors Python _ALLOWLIST)
var ssecAllowlist = []*regexp.Regexp{
	regexp.MustCompile(`(?i)(?:detect|scan|check|pattern|warn|block|deny|example|e\.g\.|blacklist|NEVER|DON'T)`),
	regexp.MustCompile(`(?i)(?:flag|signal|target|reference|attempt|mention|modify|access|write\s+to)`),
	regexp.MustCompile(`(?i)\b(?:technique|vector|attack|method|goal|override|hijack|inject|payload|exfil)\b`),
	regexp.MustCompile("```"),
	regexp.MustCompile("`[^`]+`"),
	regexp.MustCompile(`#\s+`),
	regexp.MustCompile(`^\|`),
	regexp.MustCompile(`^\*\*`),
	regexp.MustCompile(`^-\s+\*\*`),
	regexp.MustCompile(`^\d+\.\s+`),
	regexp.MustCompile(`^"[^"]+"\s*$`),
}

// curl/wget localhost patterns (allow these)
var (
	reCurl      = regexp.MustCompile(`\bcurl\s+`)
	reWget      = regexp.MustCompile(`\bwget\s+`)
	reLocalhost = regexp.MustCompile(`(?:localhost|127\.0\.0\.1|0\.0\.0\.0)`)

	// credentials allowlist: .md, documentation, example
	reCredentialsAllow = regexp.MustCompile(`(?i)(?:\.md|documentation|example)`)

	// .env.d.ts should not be flagged
	reEnvDTs = regexp.MustCompile(`\.env\.d\.ts`)
)

type ssecFinding struct {
	lineNum     int
	category    string
	description string
	content     string
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func ssecIsSkillMarkdown(filePath string) bool {
	if filePath == "" {
		return false
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return false
	}
	skillsDir := filepath.Join(home, ".claude", "skills")
	expanded := filePath
	if strings.HasPrefix(filePath, "~") {
		if filePath == "~" {
			expanded = home
		} else if strings.HasPrefix(filePath, "~/") {
			expanded = filepath.Join(home, filePath[2:])
		}
	}
	return strings.HasPrefix(expanded, skillsDir+"/") && strings.HasSuffix(expanded, ".md")
}

func ssecAllowlisted(stripped string) bool {
	for _, re := range ssecAllowlist {
		if re.MatchString(stripped) {
			return true
		}
	}
	return false
}

func ssecScanContent(content string) []ssecFinding {
	var findings []ssecFinding
	inFence := false

	for lineNum, line := range strings.Split(content, "\n") {
		lineNum++ // 1-based
		stripped := strings.TrimSpace(line)
		if stripped == "" {
			continue
		}
		if strings.HasPrefix(stripped, "```") {
			inFence = !inFence
			continue
		}
		if inFence {
			continue
		}
		if ssecAllowlisted(stripped) {
			continue
		}

		// S1 checks
		for _, p := range ssecS1 {
			if p.re.MatchString(stripped) {
				cat := p.description[:2]
				preview := stripped
				if len(preview) > 120 {
					preview = preview[:120]
				}
				findings = append(findings, ssecFinding{lineNum, cat, p.description, preview})
			}
		}

		// S2 checks
		for _, p := range ssecS2 {
			if p.re.MatchString(stripped) {
				cat := p.description[:2]
				preview := stripped
				if len(preview) > 120 {
					preview = preview[:120]
				}
				findings = append(findings, ssecFinding{lineNum, cat, p.description, preview})
			}
		}

		// S3 checks — curl/wget with non-localhost target (lookahead workaround)
		if reCurl.MatchString(stripped) && !reLocalhost.MatchString(stripped) {
			findings = append(findings, ssecFinding{lineNum, "S3", "S3: external curl (non-localhost)", stripped[:min120(stripped)]})
		}
		if reWget.MatchString(stripped) && !reLocalhost.MatchString(stripped) {
			findings = append(findings, ssecFinding{lineNum, "S3", "S3: external wget", stripped[:min120(stripped)]})
		}

		// .env (but not .env.d.ts)
		if ssecS3[0].re.MatchString(stripped) && !reEnvDTs.MatchString(stripped) {
			findings = append(findings, ssecFinding{lineNum, "S3", ssecS3[0].description, stripped[:min120(stripped)]})
		}

		// .ssh/, .aws/
		for _, p := range ssecS3[1:3] {
			if p.re.MatchString(stripped) {
				findings = append(findings, ssecFinding{lineNum, "S3", p.description, stripped[:min120(stripped)]})
			}
		}

		// credentials (but not .md / documentation / example)
		if ssecS3[3].re.MatchString(stripped) && !reCredentialsAllow.MatchString(stripped) {
			findings = append(findings, ssecFinding{lineNum, "S3", ssecS3[3].description, stripped[:min120(stripped)]})
		}

		// hardcoded secret, base64+http
		for _, p := range ssecS3[4:] {
			if p.re.MatchString(stripped) {
				findings = append(findings, ssecFinding{lineNum, "S3", p.description, stripped[:min120(stripped)]})
			}
		}
	}
	return findings
}

func min120(s string) int {
	if len(s) < 120 {
		return len(s)
	}
	return 120
}
