package core

import (
	"regexp"
	"strings"
)

// echoBlockPattern matches a header line plus optional trailing hook-output lines.
// The anchor is line-oriented ((?m) multiline mode).
//
// Structure mirrors OMC buildEchoBlockRegex:
//
//	^[ \t]*<headerBody>.*(<continuation>)?$   (per line, multiline)
//
// Continuation suffix: optional lines that look like "Task: …",
// "When FULLY complete …", or "run /oh-my-claudecode:cancel …"
const echoContinuation = `(?:\r?\n[ \t]*(?:Task:\s|When FULLY complete \(after Architect verification\)|run\s+/oh-my-claudecode:cancel).*)*`

// loopEchoPatterns matches "[XXX LOOP - ITERATION N]" style headers.
// One entry per distinct header class to stay readable.
var echoBlockPatterns = buildEchoBlockPatterns()

func buildEchoBlockPatterns() []*regexp.Regexp {
	headers := []string{
		`\[RALPH LOOP\s*-\s*ITERATION[^\]\n]*\]`,
		`\[RALPH LOOP\s*-\s*(?:HARD LIMIT|EXTENDED)\]`,
		`\[TEAM\s*-\s*Phase:[^\]\n]*\]`,
		`\[AUTOPILOT[^\]\n]*\]`,
		`\[ULTRAPILOT[^\]\n]*\]`,
		`\[ULTRAWORK[^\]\n]*\]`,
		`\[ULTRAQA[^\]\n]*\]`,
		`\[PIPELINE[^\]\n]*\]`,
		`\[SWARM[^\]\n]*\]`,
		`\[TOOL ERROR[^\]\n]*\]`,
		`\[MAGIC KEYWORD:[^\]\n]*\]`,
		`\[MAGIC KEYWORDS DETECTED:[^\]\n]*\]`,
		`Stop hook (?:blocking error|feedback|stopped continuation)`,
		`PreToolUse:[^\n]*hook additional context:`,
		`PostToolUse:[^\n]*hook additional context:`,
		// system-reminder XML block (common in CC pasted context)
		`<system-reminder>[\s\S]*?</system-reminder>`,
	}

	out := make([]*regexp.Regexp, 0, len(headers))
	for _, h := range headers {
		// Use (?im) — case-insensitive + multiline anchors
		src := `(?im)^[ \t]*` + h + `.*` + echoContinuation + `$`
		out = append(out, regexp.MustCompile(src))
	}
	return out
}

// echoSignatures are fast whole-text checks that indicate the entire
// prompt is a pasted hook output, without needing to strip first.
var echoSignatures = []*regexp.Regexp{
	regexp.MustCompile(`(?i)\bWhen FULLY complete \(after Architect verification\)\b`),
	regexp.MustCompile(`(?i)\brun\s+/oh-my-claudecode:cancel\b`),
	regexp.MustCompile(`(?i)\[RALPH LOOP\s*-\s*ITERATION\b`),
}

// successLinePattern matches repeated "hook foo: Success" lines produced
// by the hook-observatory itself when output is pasted back in.
var successLinePattern = regexp.MustCompile(`(?im)^hook [^\n]+:\s+Success\s*$`)

// echoSignatureStripPatterns mirror echoSignatures at line level. They strip
// entire lines whose body contains a fast-path signature that would otherwise
// escape echoBlockPatterns and break the detect↔strip symmetry contract.
var echoSignatureStripPatterns = []*regexp.Regexp{
	regexp.MustCompile(`(?im)^.*\bWhen FULLY complete \(after Architect verification\)\b.*$`),
	regexp.MustCompile(`(?im)^.*\brun\s+/oh-my-claudecode:cancel\b.*$`),
}

// LooksLikeSystemEcho reports whether text appears to be a pasted
// hook/stop-hook output rather than a genuine user prompt.
//
// Returns true on any of:
//   - An echoSignature substring match (fast path)
//   - Any echoBlockPattern match
//   - 3+ consecutive "hook … : Success" lines
func LooksLikeSystemEcho(text string) bool {
	if strings.TrimSpace(text) == "" {
		return false
	}
	for _, sig := range echoSignatures {
		if sig.MatchString(text) {
			return true
		}
	}
	for _, pat := range echoBlockPatterns {
		if pat.MatchString(text) {
			return true
		}
	}
	// Heuristic: 3+ successive hook-success lines = dispatcher output echo
	matches := successLinePattern.FindAllString(text, -1)
	if len(matches) >= 3 {
		return true
	}
	return false
}

// StripSystemEchoes removes all detected echo blocks, individual signature
// lines, and repeated hook-success lines from text. Matches collapse to a
// single space so surrounding context is preserved without run-together words.
//
// Callers should trim/normalize whitespace after stripping if needed.
//
// Contract: StripSystemEchoes ↔ LooksLikeSystemEcho are symmetric — any input
// that triggers detection should be neutralized by strip (modulo whitespace).
func StripSystemEchoes(text string) string {
	if strings.TrimSpace(text) == "" {
		return text
	}
	cleaned := text
	for _, pat := range echoBlockPatterns {
		cleaned = pat.ReplaceAllString(cleaned, " ")
	}
	for _, pat := range echoSignatureStripPatterns {
		cleaned = pat.ReplaceAllString(cleaned, " ")
	}
	cleaned = successLinePattern.ReplaceAllString(cleaned, " ")
	return cleaned
}
