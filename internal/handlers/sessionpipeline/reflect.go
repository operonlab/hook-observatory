package sessionpipeline

import (
	"bufio"
	"encoding/json"
	"math"
	"os"
	"regexp"
	"strings"
	"time"
)

// ---------------------------------------------------------------------------
// Failure-pattern regexes (deterministic, no LLM)
// ---------------------------------------------------------------------------

var failurePatterns = []struct {
	label string
	re    *regexp.Regexp
}{
	{"tool_not_found", regexp.MustCompile(`(?i)tool[_ ]not[_ ]found|no such tool`)},
	{"permission_denied", regexp.MustCompile(`(?i)permission denied|access denied|forbidden`)},
	{"timeout", regexp.MustCompile(`(?i)timed? ?out|timeout|deadline exceeded`)},
	{"import_error", regexp.MustCompile(`(?i)importerror|modulenotfounderror|cannot import`)},
	{"file_not_found", regexp.MustCompile(`(?i)no such file|filenotfounderror|path does not exist`)},
	{"connection_error", regexp.MustCompile(`(?i)connection refused|connection error|failed to connect`)},
	{"syntax_error", regexp.MustCompile(`(?i)syntaxerror|invalid syntax`)},
	{"rate_limit", regexp.MustCompile(`(?i)rate.?limit|too many requests|429`)},
	{"context_overflow", regexp.MustCompile(`(?i)context.?length|token.?limit|max.?tokens.*exceed`)},
	{"assertion_failed", regexp.MustCompile(`(?i)assertion(error|failed)|assert.*failed`)},
}

const (
	maxErrorMessages   = 10
	maxFailurePatterns = 20
	errorIndicatorRE   = `(?i)error|exception|failed|traceback`
)

var errorIndicatorRegex = regexp.MustCompile(errorIndicatorRE)
var completionPositiveRE = regexp.MustCompile(
	`(?i)(完成|done|finished|implemented|created|updated|fixed|summariz|let me know|成功|已|結束|好了|完畢)`,
)
var completionNegativeRE = regexp.MustCompile(
	`(?i)(let me|let'?s|i will|i'?ll|i'm going to|now i|next|繼續|接下來|我來|我去)`,
)

// transcriptStats mirrors the Python dataclass.
type transcriptStats struct {
	TotalTokens         int
	UserTokens          int
	AssistantTokens     int
	AssistantTextTokens int
	ToolCallCount       int
	ToolSuccessCount    int
	ToolErrorCount      int
	TurnCount           int
	UserMessageCount    int
	DurationSecs        int
	ErrorMessages       []string
	CompletionSignal    float64
}

// ReflectMetrics is the JSON payload mirroring Python's ReflectMetrics.to_dict.
type ReflectMetrics struct {
	SessionID          string   `json:"session_id"`
	Outcome            string   `json:"outcome"`
	QualityScore       float64  `json:"quality_score"`
	TotalTokens        int      `json:"total_tokens"`
	UserTokens         int      `json:"user_tokens"`
	AssistantTokens    int      `json:"assistant_tokens"`
	ToolCallCount      int      `json:"tool_call_count"`
	ToolSuccessCount   int      `json:"tool_success_count"`
	ToolErrorCount     int      `json:"tool_error_count"`
	ToolSuccessRate    float64  `json:"tool_success_rate"`
	ContextEfficiency  float64  `json:"context_efficiency"`
	TurnCount          int      `json:"turn_count"`
	DurationSecs       int      `json:"duration_secs"`
	ErrorMessages      []string `json:"error_messages"`
	FailurePatterns    []string `json:"failure_patterns"`
	ReflectionFed      bool     `json:"reflection_fed"`
	InvariantCount     int      `json:"invariant_count"`
	DerivedCount       int      `json:"derived_count"`
	PipelineStagesOK   int      `json:"pipeline_stages_ok"`
	PipelineStagesFail int      `json:"pipeline_stages_fail"`
	ReflectedAt        string   `json:"reflected_at"`
}

// ---------------------------------------------------------------------------
// Dynamic thresholds
// ---------------------------------------------------------------------------

func calcFailureThreshold(turn int) float64 {
	base := 0.50
	var adj float64
	if turn > 10 {
		adj = math.Min(float64(turn-10)/100.0, 0.15)
	} else {
		adj = -0.1
	}
	return math.Max(0.30, math.Min(0.65, base+adj))
}

func calcPartialErrorThreshold(turn int) float64 {
	base := 0.20
	var adj float64
	if turn > 10 {
		adj = math.Min(float64(turn-10)/200.0, 0.10)
	} else {
		adj = -0.05
	}
	return math.Max(0.10, math.Min(0.35, base+adj))
}

func calcPartialToolSuccessThreshold(turn int) float64 {
	base := 0.70
	var adj float64
	if turn > 10 {
		adj = math.Min(float64(turn-10)/200.0, 0.10)
	} else {
		adj = 0.05
	}
	return math.Max(0.50, math.Min(0.85, base-adj))
}

// ---------------------------------------------------------------------------
// JSONL parsing helpers
// ---------------------------------------------------------------------------

func estimateTokens(s string) int {
	n := len(s) / 4
	if n < 0 {
		return 0
	}
	return n
}

// extractText flattens Claude content (string or list of blocks) to plain text.
func extractText(content any) string {
	switch v := content.(type) {
	case string:
		return v
	case []any:
		var parts []string
		for _, block := range v {
			b, ok := block.(map[string]any)
			if !ok {
				continue
			}
			btype, _ := b["type"].(string)
			switch btype {
			case "text":
				if t, ok := b["text"].(string); ok {
					parts = append(parts, t)
				}
			case "tool_result":
				parts = append(parts, extractText(b["content"]))
			}
		}
		return strings.Join(parts, " ")
	}
	return ""
}

// isToolError matches Python _is_tool_error semantics.
func isToolError(block map[string]any) bool {
	if b, ok := block["is_error"].(bool); ok && b {
		return true
	}
	return errorIndicatorRegex.MatchString(extractText(block["content"]))
}

func checkCompletionSignal(lastAssistant string) float64 {
	if lastAssistant == "" {
		return 0.0
	}
	score := 0.5
	if completionPositiveRE.MatchString(lastAssistant) {
		score += 0.5
	}
	if completionNegativeRE.MatchString(lastAssistant) {
		score -= 0.3
	}
	if score < 0 {
		score = 0
	}
	if score > 1 {
		score = 1
	}
	return score
}

// parseTranscript is the Go equivalent of parse_transcript().
func parseTranscript(jsonlPath string) transcriptStats {
	stats := transcriptStats{}
	f, err := os.Open(jsonlPath)
	if err != nil {
		return stats
	}
	defer f.Close()

	var (
		firstTS           float64
		lastTS            float64
		haveFirstTS       bool
		lastAssistantText string
	)

	scanner := bufio.NewScanner(f)
	scanner.Buffer(make([]byte, 1024*1024), 32*1024*1024)
	for scanner.Scan() {
		raw := strings.TrimSpace(scanner.Text())
		if raw == "" {
			continue
		}
		var obj map[string]any
		if err := json.Unmarshal([]byte(raw), &obj); err != nil {
			continue
		}

		// Timestamp bookkeeping
		if ts, ok := asFloat(obj["timestamp"]); ok {
			if !haveFirstTS {
				firstTS = ts
				haveFirstTS = true
			}
			lastTS = ts
		} else if ts, ok := asFloat(obj["ts"]); ok {
			if !haveFirstTS {
				firstTS = ts
				haveFirstTS = true
			}
			lastTS = ts
		}

		objType, _ := obj["type"].(string)

		switch objType {
		case "user", "assistant", "message":
			role := objType
			var content any
			if msg, ok := obj["message"].(map[string]any); ok {
				if r, ok := msg["role"].(string); ok {
					role = r
				}
				content = msg["content"]
			} else {
				if r, ok := obj["role"].(string); ok {
					role = r
				}
				content = obj["content"]
			}

			text := extractText(content)
			tok := estimateTokens(text)
			stats.TotalTokens += tok

			switch role {
			case "user":
				stats.UserTokens += tok
				stats.UserMessageCount++
				if list, ok := content.([]any); ok {
					for _, item := range list {
						b, ok := item.(map[string]any)
						if !ok {
							continue
						}
						if t, _ := b["type"].(string); t != "tool_result" {
							continue
						}
						if isToolError(b) {
							stats.ToolErrorCount++
							et := extractText(b["content"])
							if et != "" && len(stats.ErrorMessages) < maxErrorMessages {
								stats.ErrorMessages = append(stats.ErrorMessages, truncate(et, 200))
							}
						} else {
							stats.ToolSuccessCount++
						}
					}
				}
			case "assistant":
				stats.AssistantTokens += tok
				stats.TurnCount++
				var textParts []string
				if list, ok := content.([]any); ok {
					for _, item := range list {
						b, ok := item.(map[string]any)
						if !ok {
							continue
						}
						switch t, _ := b["type"].(string); t {
						case "text":
							if txt, ok := b["text"].(string); ok {
								textParts = append(textParts, txt)
							}
						case "tool_use":
							stats.ToolCallCount++
						}
					}
				} else if s, ok := content.(string); ok {
					textParts = append(textParts, s)
				}
				assistantText := strings.Join(textParts, " ")
				stats.AssistantTextTokens += estimateTokens(assistantText)
				if strings.TrimSpace(assistantText) != "" {
					lastAssistantText = assistantText
				}
			}

		case "tool_result":
			isErr, _ := obj["is_error"].(bool)
			if !isErr {
				isErr = errorIndicatorRegex.MatchString(extractText(obj["content"]))
			}
			if isErr {
				stats.ToolErrorCount++
				et := extractText(obj["content"])
				if et != "" && len(stats.ErrorMessages) < maxErrorMessages {
					stats.ErrorMessages = append(stats.ErrorMessages, truncate(et, 200))
				}
			} else {
				stats.ToolSuccessCount++
			}
		}
	}

	if haveFirstTS {
		diff := lastTS - firstTS
		// Python: if diff > 1e7 assume ms → seconds
		if diff > 1e7 {
			diff = diff / 1000.0
		}
		if diff < 0 {
			diff = 0
		}
		stats.DurationSecs = int(diff)
	}

	stats.CompletionSignal = checkCompletionSignal(lastAssistantText)
	return stats
}

func asFloat(v any) (float64, bool) {
	switch x := v.(type) {
	case float64:
		return x, true
	case int:
		return float64(x), true
	case int64:
		return float64(x), true
	case json.Number:
		f, err := x.Float64()
		if err == nil {
			return f, true
		}
	}
	return 0, false
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}

// ---------------------------------------------------------------------------
// Scoring & pattern extraction
// ---------------------------------------------------------------------------

func calculateQualityScore(s transcriptStats) (string, float64) {
	total := s.ToolCallCount
	var toolSuccessRate, errorRate float64
	if total > 0 {
		toolSuccessRate = float64(s.ToolSuccessCount) / float64(total)
		errorRate = float64(s.ToolErrorCount) / float64(total)
	} else {
		toolSuccessRate = 0.5
	}

	var contextEff float64
	if s.TotalTokens > 0 {
		contextEff = float64(s.AssistantTextTokens) / float64(s.TotalTokens)
	}
	if contextEff > 1.0 {
		contextEff = 1.0
	}

	failureTh := calcFailureThreshold(s.TurnCount)
	partialErrTh := calcPartialErrorThreshold(s.TurnCount)
	partialToolTh := calcPartialToolSuccessThreshold(s.TurnCount)

	var outcome string
	if s.TurnCount == 0 || s.UserMessageCount == 0 || errorRate > failureTh {
		outcome = "failure"
	} else if errorRate > partialErrTh || toolSuccessRate < partialToolTh {
		outcome = "partial"
	} else {
		outcome = "success"
	}

	score := 0.4*toolSuccessRate + 0.3*(1.0-errorRate) + 0.2*contextEff + 0.1*s.CompletionSignal
	if score < 0 {
		score = 0
	}
	if score > 1 {
		score = 1
	}
	return outcome, round4(score)
}

func extractFailurePatterns(s transcriptStats) []string {
	found := make([]string, 0, len(failurePatterns))
	combined := strings.Join(s.ErrorMessages, " ")
	for _, fp := range failurePatterns {
		if fp.re.MatchString(combined) {
			found = append(found, fp.label)
		}
		if len(found) >= maxFailurePatterns {
			break
		}
	}
	return found
}

// ---------------------------------------------------------------------------
// Orchestration
// ---------------------------------------------------------------------------

// AnalyzeTranscript mirrors analyze_transcript() in reflect_engine.py.
func AnalyzeTranscript(jsonlPath, sessionID string) ReflectMetrics {
	stats := parseTranscript(jsonlPath)
	outcome, score := calculateQualityScore(stats)
	fp := extractFailurePatterns(stats)

	total := stats.ToolCallCount
	var toolSuccessRate, contextEff float64
	if total > 0 {
		toolSuccessRate = float64(stats.ToolSuccessCount) / float64(total)
	} else {
		toolSuccessRate = 0.5
	}
	if stats.TotalTokens > 0 {
		contextEff = float64(stats.AssistantTextTokens) / float64(stats.TotalTokens)
	}
	if contextEff > 1.0 {
		contextEff = 1.0
	}

	errs := stats.ErrorMessages
	if len(errs) > maxErrorMessages {
		errs = errs[:maxErrorMessages]
	}

	return ReflectMetrics{
		SessionID:         sessionID,
		Outcome:           outcome,
		QualityScore:      score,
		TotalTokens:       stats.TotalTokens,
		UserTokens:        stats.UserTokens,
		AssistantTokens:   stats.AssistantTokens,
		ToolCallCount:     stats.ToolCallCount,
		ToolSuccessCount:  stats.ToolSuccessCount,
		ToolErrorCount:    stats.ToolErrorCount,
		ToolSuccessRate:   round4(toolSuccessRate),
		ContextEfficiency: round4(contextEff),
		TurnCount:         stats.TurnCount,
		DurationSecs:      stats.DurationSecs,
		ErrorMessages:     errs,
		FailurePatterns:   fp,
		ReflectedAt:       reflectedAtNow(),
	}
}

func round4(f float64) float64 {
	return math.Round(f*10000) / 10000
}

// reflectedAtNow mirrors Python's datetime.now(UTC).isoformat() output —
// microsecond precision with "+00:00" offset instead of "Z".
func reflectedAtNow() string {
	return time.Now().UTC().Format("2006-01-02T15:04:05.000000-07:00")
}

// StageReflect is the Go replacement for _stage_reflect.
// DB writeback (archiver PostgreSQL) and memvault reflect_on_session feedback
// are deferred — they remain Python concerns and are outside the hot path.
func StageReflect(sessionID, transcriptPath string, stagesOK, stagesFail int) StageResult {
	start := time.Now()
	r := StageResult{Name: "reflect", Success: true}

	if transcriptPath == "" {
		// Match Python: create minimal metrics with unknown outcome.
		m := ReflectMetrics{
			SessionID:   sessionID,
			Outcome:     "unknown",
			ReflectedAt: reflectedAtNow(),
		}
		m.PipelineStagesOK = stagesOK
		m.PipelineStagesFail = stagesFail
		r.Details = reflectDetails(m)
		r.DurationMs = time.Since(start).Milliseconds()
		return r
	}

	m := AnalyzeTranscript(transcriptPath, sessionID)
	m.PipelineStagesOK = stagesOK
	m.PipelineStagesFail = stagesFail

	r.Details = reflectDetails(m)
	r.DurationMs = time.Since(start).Milliseconds()
	return r
}

func reflectDetails(m ReflectMetrics) map[string]any {
	return map[string]any{
		"outcome":           m.Outcome,
		"quality_score":     m.QualityScore,
		"tool_success_rate": m.ToolSuccessRate,
		"context_efficiency": m.ContextEfficiency,
		"turn_count":        m.TurnCount,
		"total_tokens":      m.TotalTokens,
		"db_written":        false,
		"reflection_fed":    m.ReflectionFed,
		"invariant_count":   m.InvariantCount,
		"derived_count":     m.DerivedCount,
		"failure_patterns":  m.FailurePatterns,
	}
}
