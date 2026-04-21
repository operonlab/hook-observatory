package sessionpipeline

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"regexp"
	"strings"
	"time"
)

// redactPattern mirrors SessionRedactor.RedactPattern.
type redactPattern struct {
	name        string
	category    string
	re          *regexp.Regexp
	replacement string
}

// patterns preserves the exact Python order — more specific patterns first to
// avoid greedy partial matches.
var patterns = []redactPattern{
	// Passwords
	{"sudo_password_pipe", "password",
		regexp.MustCompile(`echo\s+"[^"]*"\s*\|\s*sudo\s+-S`),
		`echo "[REDACTED:password]" | sudo -S`},
	{"sudo_password_pipe_single", "password",
		regexp.MustCompile(`echo\s+'[^']*'\s*\|\s*sudo\s+-S`),
		`echo '[REDACTED:password]' | sudo -S`},
	{"sudo_password_pipe_bare", "password",
		regexp.MustCompile(`echo\s+(\S+)\s*\|\s*sudo\s+-S`),
		`echo [REDACTED:password] | sudo -S`},
	{"password_chinese", "password",
		regexp.MustCompile(`密碼[是為：:\s]*\S+`),
		`密碼[REDACTED]`},
	{"password_english", "password",
		regexp.MustCompile(`(?i)password\s*(?:is|[:=])\s*["']?\S+`),
		`password [REDACTED]`},
	{"password_parens", "password",
		regexp.MustCompile(`(?i)password\s*\(\s*([^)]+)\s*\)`),
		`password ([REDACTED])`},
	{"password_quoted", "password",
		regexp.MustCompile(`(?i)password\s+"([^"]+)"`),
		`password "[REDACTED]"`},
	{"password_quoted_single", "password",
		regexp.MustCompile(`(?i)password\s+'([^']+)'`),
		`password '[REDACTED]'`},
	// API keys
	{"anthropic_api_key", "api_key",
		regexp.MustCompile(`sk-ant-[a-zA-Z0-9_-]{20,}`),
		`[REDACTED:anthropic_key]`},
	{"openai_api_key", "api_key",
		regexp.MustCompile(`sk-[a-zA-Z0-9_-]{20,}`),
		`[REDACTED:openai_key]`},
	{"github_token", "api_key",
		regexp.MustCompile(`gh[ps]_[A-Za-z0-9_]{30,}`),
		`[REDACTED:github_token]`},
	// Tokens
	{"bearer_token", "token",
		regexp.MustCompile(`Bearer\s+[A-Za-z0-9._-]{20,}`),
		`Bearer [REDACTED:token]`},
	// AWS
	{"aws_access_key", "aws_key",
		regexp.MustCompile(`AKIA[0-9A-Z]{16}`),
		`[REDACTED:aws_key]`},
	{"aws_secret_key", "aws_secret",
		regexp.MustCompile(`(?i)(?:aws_secret|AWS_SECRET)[^\n=]*=\s*["']?[A-Za-z0-9/+=]{30,}`),
		`[REDACTED:aws_secret]`},
	// SSH
	{"ssh_private_key", "ssh_key",
		regexp.MustCompile(`-----BEGIN\s+\S+\s+PRIVATE\s+KEY-----`),
		`[REDACTED:ssh_private_key]`},
	// DB connection strings — backref replacement keeps user prefix + @
	{"db_connection_password", "db_password",
		regexp.MustCompile(`(://\w+:)([^@]+)(@)`),
		`$1***$3`},
	// Generic catch-all (must be last)
	{"generic_secret_assignment", "generic_secret",
		regexp.MustCompile(`(?i)((?:password|secret|token|api_key|apikey|api-key)\s*[=:]\s*)["']?([^\s"',}]{4,})`),
		`${1}[REDACTED]`},
}

// redactLine applies all patterns to a single line and returns the redacted
// line plus a category-count map.
func redactLine(line string) (string, map[string]int) {
	cats := map[string]int{}
	for _, p := range patterns {
		matches := p.re.FindAllStringIndex(line, -1)
		if len(matches) == 0 {
			continue
		}
		cats[p.category] += len(matches)
		line = p.re.ReplaceAllString(line, p.replacement)
	}
	return line, cats
}

// redactValue walks a JSON value recursively, redacting every string leaf.
func redactValue(v any, cats map[string]int) (any, int) {
	switch x := v.(type) {
	case string:
		redacted, c := redactLine(x)
		total := 0
		for k, n := range c {
			cats[k] += n
			total += n
		}
		return redacted, total
	case []any:
		total := 0
		for i, item := range x {
			newItem, n := redactValue(item, cats)
			x[i] = newItem
			total += n
		}
		return x, total
	case map[string]any:
		total := 0
		for k, item := range x {
			newItem, n := redactValue(item, cats)
			x[k] = newItem
			total += n
		}
		return x, total
	}
	return v, 0
}

// redactJSONLLine parses one JSONL line, redacts string leaves, re-serialises.
// Falls back to raw-text redaction if the line is not valid JSON.
func redactJSONLLine(line string, cats map[string]int) (string, int) {
	stripped := strings.TrimRight(line, "\n")
	if stripped == "" {
		return line, 0
	}
	var obj any
	if err := json.Unmarshal([]byte(stripped), &obj); err != nil {
		// Non-JSON → raw redaction
		redacted, c := redactLine(line)
		total := 0
		for k, n := range c {
			cats[k] += n
			total += n
		}
		return redacted, total
	}
	newObj, count := redactValue(obj, cats)
	if count == 0 {
		return line, 0
	}
	// Serialise without HTML escape to match Python json.dumps ensure_ascii=False.
	buf := &strings.Builder{}
	enc := json.NewEncoder(buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(newObj); err != nil {
		return line, 0
	}
	s := buf.String() // already ends with "\n"
	return s, count
}

// StageRedact is the Go replacement for _stage_redact. It reads the JSONL
// transcript, redacts every string leaf (and non-JSON lines as a fallback),
// and writes the result back atomically.
//
// Parity gaps vs Python:
//   - We skip the SQLite processed_sessions bookkeeping. Re-running redact on
//     an unchanged file is idempotent (no further matches), so the only
//     observable difference is that dashboards tracking "last redact" won't
//     record timestamps. TODO: optional modernc.org/sqlite if needed.
func StageRedact(sessionID, transcriptPath string) StageResult {
	start := time.Now()
	r := StageResult{Name: "redact", Success: true}

	if transcriptPath == "" {
		r.Details = map[string]any{"skipped": true, "reason": "no transcript_path provided"}
		r.DurationMs = time.Since(start).Milliseconds()
		return r
	}

	info, err := os.Stat(transcriptPath)
	if err != nil || info.IsDir() {
		r.Success = false
		r.Error = fmt.Sprintf("stat: %v", err)
		r.DurationMs = time.Since(start).Milliseconds()
		return r
	}
	if !strings.HasSuffix(transcriptPath, ".jsonl") {
		r.Details = map[string]any{"skipped": true, "reason": "not a .jsonl file"}
		r.DurationMs = time.Since(start).Milliseconds()
		return r
	}

	in, err := os.Open(transcriptPath)
	if err != nil {
		r.Success = false
		r.Error = err.Error()
		r.DurationMs = time.Since(start).Milliseconds()
		return r
	}

	cats := map[string]int{}
	lineCount := 0
	totalRedactions := 0

	tmpPath := transcriptPath + ".redacting.tmp"
	out, err := os.OpenFile(tmpPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		in.Close()
		r.Success = false
		r.Error = err.Error()
		r.DurationMs = time.Since(start).Milliseconds()
		return r
	}

	scanner := bufio.NewScanner(in)
	scanner.Buffer(make([]byte, 1024*1024), 32*1024*1024)
	writer := bufio.NewWriterSize(out, 256*1024)

	for scanner.Scan() {
		lineCount++
		line := scanner.Text() + "\n"
		redacted, count := redactJSONLLine(line, cats)
		totalRedactions += count
		if _, err := writer.WriteString(redacted); err != nil {
			_ = writer.Flush()
			_ = out.Close()
			_ = in.Close()
			_ = os.Remove(tmpPath)
			r.Success = false
			r.Error = fmt.Sprintf("write: %v", err)
			r.DurationMs = time.Since(start).Milliseconds()
			return r
		}
	}
	_ = writer.Flush()
	_ = out.Close()
	_ = in.Close()

	if totalRedactions > 0 {
		if err := os.Rename(tmpPath, transcriptPath); err != nil {
			_ = os.Remove(tmpPath)
			r.Success = false
			r.Error = fmt.Sprintf("rename: %v", err)
			r.DurationMs = time.Since(start).Milliseconds()
			return r
		}
	} else {
		// No changes — discard the tmp file, leave original intact.
		_ = os.Remove(tmpPath)
	}

	r.Details = map[string]any{
		"file_path":   transcriptPath,
		"redactions":  totalRedactions,
		"categories":  cats,
		"changed":     totalRedactions > 0,
		"line_count":  lineCount,
	}
	r.DurationMs = time.Since(start).Milliseconds()
	return r
}
