"""Session Reflect Engine — pure-function JSONL analysis + quality scoring.

No external dependencies beyond stdlib.  All metrics are computed
deterministically from the transcript JSONL produced by Claude Code.

Public API:
    analyze_transcript(path: str | Path) -> ReflectMetrics
    calculate_quality_score(stats: TranscriptStats) -> tuple[str, float]

Internal dataclasses:
    TranscriptStats — raw parsed counts from JSONL
    ReflectMetrics  — final scored output (sent to DB + memvault)
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

sys.path.insert(0, "/Users/joneshong/workshop/core")

# ---------------------------------------------------------------------------
# Failure-pattern regexes (deterministic, no LLM)
# ---------------------------------------------------------------------------

_FAILURE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("tool_not_found", re.compile(r"tool[_ ]not[_ ]found|no such tool", re.I)),
    ("permission_denied", re.compile(r"permission denied|access denied|forbidden", re.I)),
    ("timeout", re.compile(r"timed? ?out|timeout|deadline exceeded", re.I)),
    ("import_error", re.compile(r"importerror|modulenotfounderror|cannot import", re.I)),
    ("file_not_found", re.compile(r"no such file|filenotfounderror|path does not exist", re.I)),
    (
        "connection_error",
        re.compile(
            r"connection refused|connection error|failed to connect",
            re.I,
        ),
    ),
    ("syntax_error", re.compile(r"syntaxerror|invalid syntax", re.I)),
    ("rate_limit", re.compile(r"rate.?limit|too many requests|429", re.I)),
    ("context_overflow", re.compile(r"context.?length|token.?limit|max.?tokens.*exceed", re.I)),
    ("assertion_failed", re.compile(r"assertion(error|failed)|assert.*failed", re.I)),
]

_MAX_ERROR_MESSAGES = 10
_MAX_FAILURE_PATTERNS = 20

# Outcome thresholds — dynamic based on session length (turn count).
# Short sessions (< 10 turns) are more tolerant of errors.


def _calc_failure_threshold(turn_count: int) -> float:
    """Failure error-rate threshold: rises slightly for longer sessions."""
    base = 0.50
    adjustment = min((turn_count - 10) / 100, 0.15) if turn_count > 10 else -0.1
    return max(0.30, min(0.65, base + adjustment))


def _calc_partial_error_threshold(turn_count: int) -> float:
    """Partial error-rate threshold: rises slightly for longer sessions."""
    base = 0.20
    adjustment = min((turn_count - 10) / 200, 0.10) if turn_count > 10 else -0.05
    return max(0.10, min(0.35, base + adjustment))


def _calc_partial_tool_success_threshold(turn_count: int) -> float:
    """Partial tool-success-rate threshold: loosens slightly for longer sessions."""
    base = 0.70
    adjustment = min((turn_count - 10) / 200, 0.10) if turn_count > 10 else 0.05
    return max(0.50, min(0.85, base - adjustment))


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class TranscriptStats:
    """Raw counts extracted from a transcript JSONL."""

    # Token estimates (len(text) // 4)
    total_tokens: int = 0
    user_tokens: int = 0
    assistant_tokens: int = 0
    assistant_text_tokens: int = 0  # text-only, excludes tool_call serialisation

    # Tool call tracking
    tool_call_count: int = 0
    tool_success_count: int = 0
    tool_error_count: int = 0

    # Session shape
    turn_count: int = 0
    user_message_count: int = 0
    duration_secs: int = 0

    # Error content (first _MAX_ERROR_MESSAGES entries)
    error_messages: list[str] = field(default_factory=list)

    # Completion signal: did the final assistant message look like a conclusion?
    completion_signal: float = 0.0


@dataclass
class ReflectMetrics:
    """Final reflect output — stored to DB and optionally fed to memvault."""

    session_id: str

    # Outcome classification
    outcome: Literal["success", "partial", "failure", "unknown"] = "unknown"
    quality_score: float = 0.0

    # Token metrics
    total_tokens: int = 0
    user_tokens: int = 0
    assistant_tokens: int = 0

    # Tool metrics
    tool_call_count: int = 0
    tool_success_count: int = 0
    tool_error_count: int = 0
    tool_success_rate: float = 0.0

    # Context efficiency
    context_efficiency: float = 0.0

    # Session shape
    turn_count: int = 0
    duration_secs: int = 0

    # Extracted failure info (truncated)
    error_messages: list[str] = field(default_factory=list)
    failure_patterns: list[str] = field(default_factory=list)

    # Memvault integration (set after HTTP call)
    reflection_fed: bool = False
    invariant_count: int = 0
    derived_count: int = 0

    # Pipeline context (filled by SDK)
    pipeline_stages_ok: int = 0
    pipeline_stages_fail: int = 0

    # Timestamps
    reflected_at: str = ""

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "outcome": self.outcome,
            "quality_score": round(self.quality_score, 4),
            "total_tokens": self.total_tokens,
            "user_tokens": self.user_tokens,
            "assistant_tokens": self.assistant_tokens,
            "tool_call_count": self.tool_call_count,
            "tool_success_count": self.tool_success_count,
            "tool_error_count": self.tool_error_count,
            "tool_success_rate": round(self.tool_success_rate, 4),
            "context_efficiency": round(self.context_efficiency, 4),
            "turn_count": self.turn_count,
            "duration_secs": self.duration_secs,
            "error_messages": self.error_messages,
            "failure_patterns": self.failure_patterns,
            "reflection_fed": self.reflection_fed,
            "invariant_count": self.invariant_count,
            "derived_count": self.derived_count,
            "pipeline_stages_ok": self.pipeline_stages_ok,
            "pipeline_stages_fail": self.pipeline_stages_fail,
            "reflected_at": self.reflected_at,
        }


# ---------------------------------------------------------------------------
# JSONL parsing
# ---------------------------------------------------------------------------


def _estimate_tokens(text: str) -> int:
    """Simple token estimate: len(text) // 4."""
    return max(0, len(text) // 4)


def _extract_text(content: object) -> str:
    """Flatten a Claude content block (str or list of dicts) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type", "")
            if btype == "text":
                parts.append(block.get("text", ""))
            elif btype == "tool_result":
                # Nested content inside tool_result
                inner = block.get("content", "")
                parts.append(_extract_text(inner))
        return " ".join(parts)
    return ""


def _is_tool_error(block: dict) -> bool:
    """Return True if this tool_result block indicates an error."""
    # Claude sets is_error=True or wraps content in error markers
    if block.get("is_error"):
        return True
    # Also check nested content text for common error signals
    inner = _extract_text(block.get("content", ""))
    if re.search(r"error|exception|failed|traceback", inner, re.I):
        return True
    return False


def _check_completion_signal(last_assistant_text: str) -> float:
    """Heuristic: does the last assistant message look like a conclusion?"""
    if not last_assistant_text:
        return 0.0
    # Positive signals
    positive = re.search(
        r"(完成|done|finished|implemented|created|updated|fixed|summariz|let me know|"
        r"成功|已|結束|好了|完畢)",
        last_assistant_text,
        re.I,
    )
    # Negative signals (mid-task language)
    negative = re.search(
        r"(let me|let'?s|i will|i'?ll|i'm going to|now i|next|繼續|接下來|我來|我去)",
        last_assistant_text,
        re.I,
    )
    score = 0.5
    if positive:
        score += 0.5
    if negative:
        score -= 0.3
    return max(0.0, min(1.0, score))


def parse_transcript(jsonl_path: str | Path) -> TranscriptStats:
    """Parse a Claude transcript JSONL file and return raw stats.

    The JSONL format contains one JSON object per line.  Each line is a
    Claude Code hook event with a ``type`` field.  We handle:
      - ``message``     — a full conversation turn (role + content array)
      - ``tool_result`` — outcome of a single tool invocation

    Unknown line types are silently skipped.
    """
    path = Path(jsonl_path)
    stats = TranscriptStats()

    if not path.exists():
        return stats

    first_ts: float | None = None
    last_ts: float | None = None
    last_assistant_text = ""

    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for raw_line in fh:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    obj = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue

                # Timestamp bookkeeping
                ts = obj.get("timestamp") or obj.get("ts")
                if isinstance(ts, (int, float)):
                    if first_ts is None:
                        first_ts = ts
                    last_ts = ts

                obj_type = obj.get("type", "")

                # ----------------------------------------------------------
                # message event: role + content
                # ----------------------------------------------------------
                if obj_type == "message":
                    role = obj.get("role", "")
                    content = obj.get("content", "")

                    text = _extract_text(content)
                    tok = _estimate_tokens(text)
                    stats.total_tokens += tok

                    if role == "user":
                        stats.user_tokens += tok
                        stats.user_message_count += 1
                    elif role == "assistant":
                        stats.assistant_tokens += tok
                        stats.turn_count += 1

                        # Separate text tokens from tool_call tokens
                        text_only_parts: list[str] = []
                        if isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict):
                                    if block.get("type") == "text":
                                        text_only_parts.append(block.get("text", ""))
                                    elif block.get("type") == "tool_use":
                                        # Count tool calls
                                        stats.tool_call_count += 1
                        elif isinstance(content, str):
                            text_only_parts.append(content)

                        assistant_text = " ".join(text_only_parts)
                        stats.assistant_text_tokens += _estimate_tokens(assistant_text)
                        if assistant_text.strip():
                            last_assistant_text = assistant_text

                # ----------------------------------------------------------
                # tool_result event (separate line in some transcript formats)
                # ----------------------------------------------------------
                elif obj_type == "tool_result":
                    is_err = obj.get("is_error", False)
                    content_val = obj.get("content", "")
                    if not is_err:
                        is_err = bool(
                            re.search(
                                r"error|exception|failed|traceback",
                                _extract_text(content_val),
                                re.I,
                            )
                        )
                    if is_err:
                        stats.tool_error_count += 1
                        err_text = _extract_text(content_val)
                        if err_text and len(stats.error_messages) < _MAX_ERROR_MESSAGES:
                            stats.error_messages.append(err_text[:200])
                    else:
                        stats.tool_success_count += 1

                # ----------------------------------------------------------
                # Inline tool_result inside message content blocks
                # ----------------------------------------------------------
                elif obj_type == "message" and False:
                    pass  # handled above; kept for clarity

    except OSError:
        return stats

    # Duration from timestamps (prefer epoch seconds; if ms, divide by 1000)
    if first_ts is not None and last_ts is not None:
        diff = last_ts - first_ts
        # If timestamps look like milliseconds (> 1e10), convert to seconds
        if diff > 1e7:
            diff = diff / 1000.0
        stats.duration_secs = max(0, int(diff))

    # Scan assistant messages for inline tool_result blocks we may have missed
    # (some transcript formats embed results inside the message content list)
    # This pass is already handled above.  Recalculate tool counts from content.

    stats.completion_signal = _check_completion_signal(last_assistant_text)
    return stats


# ---------------------------------------------------------------------------
# Quality scoring
# ---------------------------------------------------------------------------


def calculate_quality_score(stats: TranscriptStats) -> tuple[str, float]:
    """Compute (outcome, quality_score) from TranscriptStats.

    outcome: "success" | "partial" | "failure"
    quality_score: float in [0.0, 1.0]

    Formula:
        score = 0.4 * tool_success_rate
              + 0.3 * (1 - error_rate)
              + 0.2 * context_efficiency
              + 0.1 * completion_signal
    """
    # Derived rates
    total_calls = stats.tool_call_count
    tool_success_rate = stats.tool_success_count / total_calls if total_calls > 0 else 1.0
    error_rate = stats.tool_error_count / total_calls if total_calls > 0 else 0.0
    context_efficiency = (
        stats.assistant_text_tokens / stats.total_tokens if stats.total_tokens > 0 else 0.0
    )
    context_efficiency = min(1.0, context_efficiency)

    # Outcome classification (dynamic thresholds based on session length)
    failure_threshold = _calc_failure_threshold(stats.turn_count)
    partial_error_threshold = _calc_partial_error_threshold(stats.turn_count)
    partial_tool_threshold = _calc_partial_tool_success_threshold(stats.turn_count)
    if stats.turn_count == 0 or stats.user_message_count == 0 or error_rate > failure_threshold:
        outcome = "failure"
    elif error_rate > partial_error_threshold or tool_success_rate < partial_tool_threshold:
        outcome = "partial"
    else:
        outcome = "success"

    # Score (clamped to [0, 1])
    score = (
        0.4 * tool_success_rate
        + 0.3 * (1.0 - error_rate)
        + 0.2 * context_efficiency
        + 0.1 * stats.completion_signal
    )
    score = max(0.0, min(1.0, score))

    return outcome, round(score, 4)


# ---------------------------------------------------------------------------
# Failure pattern extraction
# ---------------------------------------------------------------------------


def extract_failure_patterns(stats: TranscriptStats) -> list[str]:
    """Scan error_messages for known failure patterns and return matched labels."""
    found: list[str] = []
    combined = " ".join(stats.error_messages)
    for label, pattern in _FAILURE_PATTERNS:
        if pattern.search(combined):
            found.append(label)
        if len(found) >= _MAX_FAILURE_PATTERNS:
            break
    return found


def classify_failures_rlm(
    error_messages: list[str],
    failure_patterns: list[str],
    timeout: int = 45,
) -> dict | None:
    """Semantic failure classification using RLM engine.

    Only call when len(error_messages) > 5 — small sessions use regex.
    Returns {"categories": [{"name", "count", "root_cause", "suggested_fix"}]}
    or None on failure (caller should use extract_failure_patterns instead).
    """
    if len(error_messages) <= 5:
        return None

    # Build context from error messages
    error_context = "\n".join(f"[Error {i + 1}] {msg}" for i, msg in enumerate(error_messages))
    if failure_patterns:
        error_context += "\n\nRegex-detected patterns: " + ", ".join(failure_patterns)

    prompt = (
        "Analyze these error messages from a Claude Code session and classify them.\n\n"
        "Output ONLY valid JSON:\n"
        "{\n"
        '  "categories": [\n'
        "    {\n"
        '      "name": "category name (e.g. permission_denied, network_error, syntax_error)",\n'
        '      "count": <number of errors in this category>,\n'
        '      "root_cause": "likely root cause (1 sentence)",\n'
        '      "suggested_fix": "actionable fix suggestion (1 sentence)"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "- Group similar errors into categories\n"
        "- Use snake_case for category names\n"
        "- Be specific about root causes, not generic\n"
        "- Limit to max 10 categories\n"
        "- Output ONLY the JSON object, no markdown"
    )

    try:
        from src.shared.rlm_engine import RLMConfig, RLMEngine

        engine = RLMEngine(
            RLMConfig(
                model="grok-4-fast",
                max_iterations=5,
                max_timeout_secs=timeout,
                api_base="http://localhost:4000/v1",
                api_key="sk-litellm-local-dev",
            )
        )
        result = engine.completion(prompt=prompt, context=error_context)

        if result.status != "ok" or not result.response:
            return None

        # Parse JSON from response
        raw = result.response.strip()
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not json_match:
            return None

        data = json.loads(json_match.group())

        if "categories" not in data or not isinstance(data["categories"], list):
            return None

        # Validate and sanitize categories
        clean_cats = []
        for cat in data["categories"][:10]:
            if not isinstance(cat, dict):
                continue
            clean_cats.append(
                {
                    "name": str(cat.get("name", "unknown"))[:50],
                    "count": int(cat.get("count", 1)),
                    "root_cause": str(cat.get("root_cause", ""))[:200],
                    "suggested_fix": str(cat.get("suggested_fix", ""))[:200],
                }
            )

        return {"categories": clean_cats} if clean_cats else None

    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def analyze_transcript(jsonl_path: str | Path, session_id: str = "") -> ReflectMetrics:
    """Full analysis pipeline: parse → score → extract patterns.

    Args:
        jsonl_path:  Path to the Claude transcript JSONL file.
        session_id:  Session ID to embed in the returned ReflectMetrics.

    Returns:
        ReflectMetrics dataclass with all computed fields.
    """
    from datetime import UTC, datetime

    stats = parse_transcript(jsonl_path)
    outcome, quality_score = calculate_quality_score(stats)
    failure_patterns = extract_failure_patterns(stats)

    total_calls = stats.tool_call_count
    tool_success_rate = stats.tool_success_count / total_calls if total_calls > 0 else 1.0
    context_efficiency = (
        stats.assistant_text_tokens / stats.total_tokens if stats.total_tokens > 0 else 0.0
    )
    context_efficiency = min(1.0, context_efficiency)

    return ReflectMetrics(
        session_id=session_id,
        outcome=outcome,
        quality_score=quality_score,
        total_tokens=stats.total_tokens,
        user_tokens=stats.user_tokens,
        assistant_tokens=stats.assistant_tokens,
        tool_call_count=stats.tool_call_count,
        tool_success_count=stats.tool_success_count,
        tool_error_count=stats.tool_error_count,
        tool_success_rate=round(tool_success_rate, 4),
        context_efficiency=round(context_efficiency, 4),
        turn_count=stats.turn_count,
        duration_secs=stats.duration_secs,
        error_messages=stats.error_messages[:_MAX_ERROR_MESSAGES],
        failure_patterns=failure_patterns,
        reflected_at=datetime.now(UTC).isoformat(),
    )


# ---------------------------------------------------------------------------
# CLI shim for quick smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python3 reflect_engine.py <transcript.jsonl> [session_id]")
        sys.exit(1)

    _path = sys.argv[1]
    _sid = sys.argv[2] if len(sys.argv) > 2 else "test"
    metrics = analyze_transcript(_path, _sid)
    import json as _json

    print(_json.dumps(metrics.to_dict(), indent=2, ensure_ascii=False))
