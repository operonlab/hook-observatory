"""
Context Supervisor — three-layer context health monitoring.

Layer 1: Context pressure (reads StatusLine bridge JSON for window %)
Layer 2: Heuristic drift (tool-pattern analysis: re-reads, repetition, cycling, etc.)
Layer 3: LLM + Embedding semantic coherence (periodic, background headless call + oMLX)

Cannibalized from: StatusLine+Hook Bridge, Context Rotation, Continuous Claude v3,
Post-Compact Recovery.

State: /tmp/claude-supervisor-{session_id}.json
Events: SessionStart, PostToolUse, Stop, UserPromptSubmit, PreCompact

v2: Security hardening (shell injection fix, atomic writes), confidence ramp,
    token velocity, specific suggestions, selective compact reset.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, "/Users/joneshong/workshop/core")

from .base import ALLOW, HookResult, text_result

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CACHE_DIR = "/tmp/.claude-statusline"  # noqa: S108
_STATE_PREFIX = "/tmp/claude-supervisor"  # noqa: S108
_LLM_PREFIX = "/tmp/claude-supervisor-llm"  # noqa: S108
_PROMPT_PREFIX = "/tmp/claude-supervisor-prompt"  # noqa: S108 — safe prompt file for LLM

# Layer 2 thresholds
_REREAD_WINDOW = 20
_TOOL_REP_WINDOW = 15
_PROGRESS_WINDOW = 20
_PROGRESS_WARN_RATIO = 0.10
_CMD_RETRY_WINDOW = 15
_SCOPE_FREEZE_TURN = 10

# Layer 2 composite weights
# NOTE: file_reread and tool_repetition overlap (same Read call counted in both).
# Reduced tool_repetition weight and excluded Read from it to avoid double-counting.
_WEIGHTS = {
    "file_reread": 0.20,
    "tool_repetition": 0.15,
    "edit_cycling": 0.25,
    "empty_progress": 0.20,
    "command_retry": 0.15,
    "scope_drift": 0.05,
}

# Context pressure thresholds (base — scaled by confidence ramp)
_CTX_WARN_DEFAULT = 70
_CTX_WARN_DRIFT = 60
_CTX_CRITICAL = 80
_CTX_CRITICAL_DRIFT = 75

# Debounce
_SUGGEST_COOLDOWN = 3
_MAX_SUGGESTS = 5
_LLM_COOLDOWN = 5
_LLM_PERIOD = 10

# Whitelists
_REREAD_WHITELIST = {"CLAUDE.md", "package.json", "pyproject.toml", "tsconfig.json"}
_IDEMPOTENT_CMDS = {"git status", "git diff", "git log", "ls", "pwd", "whoami"}
_PRODUCTIVE_TOOLS = {"Write", "Edit", "Agent", "Skill"}

# Embedding
_OMLX_URL = "http://localhost:8000/v1/embeddings"
_EMBED_MODEL = "qwen-embedding-0.6B"
_EMBED_TIMEOUT = 5

# Layer 3 weights: LLM : Embedding = 1 : 0.3
_LLM_WEIGHT = 1.0 / 1.3  # ~0.77
_EMBED_WEIGHT = 0.3 / 1.3  # ~0.23


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    # Quiet mode: CTX_SUPERVISOR_LEVEL=off|critical|warn (default: warn)
    level = os.environ.get("CTX_SUPERVISOR_LEVEL", "warn")
    if level == "off":
        return ALLOW

    try:
        session_id = _extract_session_id(raw_input)
        if not session_id:
            return ALLOW

        if event_type == "SessionStart":
            return _on_session_start(session_id)
        if event_type == "PreCompact":
            return _on_pre_compact(session_id)

        state = _load_state(session_id)
        if not state:
            return ALLOW

        if event_type == "PostToolUse":
            return _on_post_tool(state, session_id, tool_name, tool_input)
        if event_type == "Stop":
            return _on_stop(state, session_id)
        if event_type == "UserPromptSubmit":
            return _on_prompt(state, session_id, raw_input)

    except Exception:  # noqa: S110
        pass
    return ALLOW


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------


def _on_session_start(session_id: str) -> HookResult:
    state = _new_state(session_id)
    _save_state(session_id, state)
    # Clean up stale files from previous session
    for prefix in (_LLM_PREFIX, _PROMPT_PREFIX):
        path = f"{prefix}-{session_id}.json"
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:  # noqa: S110
            pass
    return ALLOW


def _on_pre_compact(session_id: str) -> HookResult:
    """Selective reset: clear context-dependent signals, keep behavioral patterns."""
    state = _load_state(session_id)
    if state:
        state["escalation"] = "normal"
        state["suggest_count"] = 0
        # Clear context-dependent signals (files may no longer be in context)
        state["file_reads"] = {}
        state["tool_hashes"] = {}
        state["bash_commands"] = []
        state["progress_window"] = []
        # Keep: file_mutations (edit cycling is behavioral, not context-dependent)
        # Keep: scope_violations (scope drift is cumulative)
        # Keep: Layer 3 scores (still valid for topic coherence)
        _save_state(session_id, state)
    return ALLOW


def _on_post_tool(state: dict, session_id: str, tool_name: str, tool_input: dict) -> HookResult:
    state["tool_calls"] = state.get("tool_calls", 0) + 1

    if tool_name in ("Write", "Edit"):
        state["edit_count"] = state.get("edit_count", 0) + 1

    # Track recent tools (sliding window)
    recent = state.get("recent_tools", [])
    recent.append(tool_name)
    state["recent_tools"] = recent[-_PROGRESS_WINDOW:]

    # Track file paths for scope
    file_path = tool_input.get("file_path", tool_input.get("path", ""))
    if file_path:
        _track_scope(state, file_path)

    # Signal 1: File re-read
    if tool_name == "Read" and file_path:
        _track_file_read(state, file_path)

    # Signal 2: Tool repetition
    _track_tool_hash(state, tool_name, tool_input)

    # Signal 3: Edit cycling — track mutations
    if tool_name in ("Write", "Edit") and file_path:
        mutations = state.setdefault("file_mutations", {})
        entry = mutations.setdefault(file_path, {"writes": [], "reads_after": [], "cycles": 0})
        entry["writes"].append(state.get("turn_count", 0))
        entry["writes"] = entry["writes"][-10:]
        # Cap file_mutations entries
        if len(mutations) > 30:
            oldest = min(mutations, key=lambda k: max(mutations[k].get("writes", [0])))
            del mutations[oldest]
    elif tool_name == "Read" and file_path:
        mutations = state.get("file_mutations", {})
        if file_path in mutations and mutations[file_path]["writes"]:
            mutations[file_path].setdefault("reads_after", []).append(state.get("turn_count", 0))
            mutations[file_path]["reads_after"] = mutations[file_path]["reads_after"][-10:]

    # Signal 4: Progress tracking
    progress = state.setdefault("progress_window", [])
    is_productive = tool_name in _PRODUCTIVE_TOOLS
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        if _is_productive_cmd(cmd):
            is_productive = True
    progress.append(
        {"turn": state.get("turn_count", 0), "tool": tool_name, "productive": is_productive}
    )
    state["progress_window"] = progress[-_PROGRESS_WINDOW:]

    # Signal 5: Command retry
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        _track_bash_cmd(state, cmd)

    # Compute Layer 2 composite (pass turn for confidence dampening + state for bonus)
    scores = _compute_signal_scores(state)
    state["signal_scores"] = scores
    state["composite_score"] = _composite(scores, state.get("turn_count", 0), state)

    _save_state(session_id, state)
    return ALLOW


def _on_stop(state: dict, session_id: str) -> HookResult:
    state["turn_count"] = state.get("turn_count", 0) + 1

    # Track context velocity (ctx% history for growth rate detection)
    ctx_pct = state.get("last_ctx_pct", 0)
    if ctx_pct > 0:
        history = state.setdefault("ctx_history", [])
        history.append({"turn": state["turn_count"], "pct": ctx_pct})
        state["ctx_history"] = history[-10:]  # keep last 10 data points

    # Maybe trigger Layer 3 analysis
    _maybe_trigger_layer3(state, session_id)

    _save_state(session_id, state)
    return ALLOW


def _on_prompt(state: dict, session_id: str, raw_input: str) -> HookResult:
    # Record user prompt
    user_prompt = _extract_user_prompt(raw_input)
    if user_prompt:
        prompts = state.setdefault("recent_user_prompts", [])
        prompts.append(user_prompt[:500])
        state["recent_user_prompts"] = prompts[-5:]

    # Read Layer 1: context pressure
    ctx_pct = _read_ctx_bridge()
    if ctx_pct is not None:
        state["last_ctx_pct"] = ctx_pct

    # Read Layer 3 results
    _consume_llm_result(state, session_id)

    # Check quiet mode
    level = os.environ.get("CTX_SUPERVISOR_LEVEL", "warn")

    # Check debounce
    turn = state.get("turn_count", 0)
    last = state.get("last_suggest_turn", 0)
    count = state.get("suggest_count", 0)
    if turn - last < _SUGGEST_COOLDOWN or count >= _MAX_SUGGESTS:
        _save_state(session_id, state)
        return ALLOW

    # Evaluate escalation
    suggestion = _evaluate(state)
    if suggestion:
        # Quiet mode: only emit critical-level suggestions
        if level == "critical" and suggestion["level"] != "critical":
            _save_state(session_id, state)
            return ALLOW

        state["last_suggest_turn"] = turn
        state["suggest_count"] = count + 1
        state["escalation"] = suggestion["level"]
        _save_state(session_id, state)
        return text_result(suggestion["text"])

    _save_state(session_id, state)
    return ALLOW


# ---------------------------------------------------------------------------
# Layer 1: Context pressure (read StatusLine bridge)
# ---------------------------------------------------------------------------


def _read_ctx_bridge() -> float | None:
    pane = os.environ.get("TMUX_PANE", str(os.getpid()))
    pane_safe = pane.replace("%", "")
    path = f"{_CACHE_DIR}/ctx-{pane_safe}.json"
    try:
        data = json.loads(Path(path).read_text())
        ts = data.get("ts", 0)
        if time.time() - ts > 30:
            return None
        return float(data.get("pct", 0))
    except Exception:
        return None


def _compute_ctx_velocity(state: dict) -> float:
    """Compute context % growth rate (pct per turn). 0 if insufficient data."""
    history = state.get("ctx_history", [])
    if len(history) < 3:
        return 0.0
    recent = history[-5:]
    if len(recent) < 2:
        return 0.0
    delta_pct = recent[-1]["pct"] - recent[0]["pct"]
    delta_turns = recent[-1]["turn"] - recent[0]["turn"]
    return delta_pct / delta_turns if delta_turns > 0 else 0.0


# ---------------------------------------------------------------------------
# Layer 2: Signal tracking & scoring
# ---------------------------------------------------------------------------


def _track_file_read(state: dict, file_path: str) -> None:
    basename = os.path.basename(file_path)
    if basename in _REREAD_WHITELIST:
        return

    reads = state.setdefault("file_reads", {})
    entry = reads.setdefault(file_path, {"count": 0, "turns": []})
    entry["count"] += 1
    entry["turns"].append(state.get("turn_count", 0))
    entry["turns"] = entry["turns"][-_REREAD_WINDOW:]

    if len(reads) > 50:
        oldest = min(reads, key=lambda k: max(reads[k]["turns"], default=0))
        del reads[oldest]


def _track_tool_hash(state: dict, tool_name: str, tool_input: dict) -> None:
    canonical = _canonicalize_input(tool_name, tool_input)
    h = hashlib.sha256(f"{tool_name}:{canonical}".encode()).hexdigest()[:12]

    hashes = state.setdefault("tool_hashes", {})
    entry = hashes.setdefault(h, {"count": 0, "turns": [], "tool": tool_name})
    entry["count"] += 1
    entry["turns"].append(state.get("turn_count", 0))
    entry["turns"] = entry["turns"][-_TOOL_REP_WINDOW:]

    if len(hashes) > 100:
        oldest = min(hashes, key=lambda k: max(hashes[k]["turns"], default=0))
        del hashes[oldest]


def _track_scope(state: dict, file_path: str) -> None:
    parts = file_path.split("/")
    if len(parts) < 4:
        return
    module_dir = "/".join(parts[:4])

    turn = state.get("turn_count", 0)
    scope_paths = state.setdefault("initial_scope_paths", [])

    if turn < _SCOPE_FREEZE_TURN:  # Fixed: < instead of <= to avoid off-by-one
        if module_dir not in scope_paths:
            scope_paths.append(module_dir)
    else:
        state["scope_frozen"] = True
        if not _in_scope(module_dir, scope_paths):
            violations = state.setdefault("scope_violations", [])
            violations.append({"turn": turn, "path": module_dir})
            state["scope_violations"] = violations[-30:]


def _track_bash_cmd(state: dict, cmd: str) -> None:
    normalized = _normalize_bash(cmd)
    if not normalized or normalized in _IDEMPOTENT_CMDS:
        return

    cmds = state.setdefault("bash_commands", [])
    cmds.append({"turn": state.get("turn_count", 0), "cmd": cmd, "norm": normalized})
    state["bash_commands"] = cmds[-50:]


def _compute_signal_scores(state: dict) -> dict:
    turn = state.get("turn_count", 0)
    scores: dict[str, float] = {}

    # Signal 1: File re-read — also track worst offender for specific suggestion
    # Threshold raised: normal dev reads a file 5-6 times easily (read→edit→verify)
    max_reread = 0
    worst_file = ""
    for fp, entry in state.get("file_reads", {}).items():
        recent = [t for t in entry.get("turns", []) if t > turn - _REREAD_WINDOW]
        if len(recent) > max_reread:
            max_reread = len(recent)
            worst_file = fp
    scores["file_reread"] = min(100, max(0, (max_reread - 2) * 25))
    if worst_file and max_reread >= 3:
        state["_worst_reread"] = f"{os.path.basename(worst_file)} ({max_reread}x)"

    # Signal 2: Tool repetition — exclude Read (already tracked by file_reread)
    max_rep = 0
    for entry in state.get("tool_hashes", {}).values():
        if entry.get("tool") == "Read":
            continue  # avoid double-counting with file_reread
        recent = [t for t in entry.get("turns", []) if t > turn - _TOOL_REP_WINDOW]
        max_rep = max(max_rep, len(recent))
    scores["tool_repetition"] = min(100, max(0, (max_rep - 1) * 30))

    # Signal 3: Edit cycling — detect write→read→rewrite loops on the SAME file.
    # Normal dev: 1-2 writes with reads in between is fine. Flag ≥3 writes
    # with interleaved reads (a sign the agent is stuck editing the same spot).
    total_cycles = sum(entry.get("cycles", 0) for entry in state.get("file_mutations", {}).values())
    worst_cycle_file = ""
    for fp, entry in state.get("file_mutations", {}).items():
        reads_after = len(entry.get("reads_after", []))
        writes = len(entry.get("writes", []))
        if writes >= 3 and reads_after >= writes - 1:
            total_cycles += 1
            worst_cycle_file = os.path.basename(fp)
    scores["edit_cycling"] = min(100, total_cycles * 30)
    if worst_cycle_file and total_cycles >= 2:
        state["_worst_cycling"] = f"{worst_cycle_file} ({total_cycles} cycles)"

    # Signal 4: Empty progress (skip first 20 turns — exploration phase)
    progress = state.get("progress_window", [])
    if len(progress) >= _PROGRESS_WINDOW and turn > 20:
        productive = sum(1 for e in progress if e.get("productive"))
        ratio = productive / len(progress)
        if ratio == 0:
            scores["empty_progress"] = 80
        elif ratio < 0.05:
            scores["empty_progress"] = 60
        elif ratio < _PROGRESS_WARN_RATIO:
            scores["empty_progress"] = 30
        else:
            scores["empty_progress"] = 0
    else:
        scores["empty_progress"] = 0

    # Signal 5: Command retry
    cmds = state.get("bash_commands", [])
    recent_cmds = [c for c in cmds if c.get("turn", 0) > turn - _CMD_RETRY_WINDOW]
    norm_counts: dict[str, int] = {}
    for c in recent_cmds:
        n = c.get("norm", "")
        norm_counts[n] = norm_counts.get(n, 0) + 1
    max_similar = max(norm_counts.values(), default=0)
    scores["command_retry"] = min(100, max(0, (max_similar - 1) * 30))

    # Signal 6: Scope drift
    violations = state.get("scope_violations", [])
    recent_v = [v for v in violations if v.get("turn", 0) > turn - 30]
    scores["scope_drift"] = min(100, max(0, (len(recent_v) - 2) * 20))

    return scores


def _composite(scores: dict, turn: int = 0, state: dict | None = None) -> int:
    """Compute composite health score blending Layer 2 (tool health) and Layer 3 (coherence).

    Formula: 60% Layer2 + 40% Layer3 - streak²x5 (when Layer 3 available).
    - Early turns have low confidence -> penalties suppressed.
    - Sessions with productive work earn a modest bonus.
    - Layer 3 coherence (LLM + embedding) pulls the score down when topic drifts.
    - Diverge streak penalty applied directly: streak²x5 ensures 3 consecutive
      divergence steps trigger red alert (< 40).

    Target behavior:
      streak 0 → green (80+), streak 1 → yellow (~67),
      streak 2 → orange (~45), streak 3 → red (~18), streak 4 → 0.
    """
    penalty = sum(scores.get(k, 0) * w for k, w in _WEIGHTS.items())
    # Dampen penalty by confidence: early turns → penalty reduced
    conf = _confidence_multiplier(turn)
    dampened = penalty * min(conf, 1.0)  # cap at 1.0 — strict mode (>1.0) only for _evaluate

    # Productivity bonus: active development earns tolerance for re-reads etc.
    bonus = _productivity_bonus(state) if state else 0

    layer2 = max(0, min(100, 100 - dampened + bonus))

    # Blend with Layer 3 coherence if available (40% weight — coherence matters)
    layer3 = _compute_layer3_score(state) if state else None
    if layer3 is not None:
        blended = layer2 * 0.6 + layer3 * 0.4
    else:
        blended = layer2

    # Direct diverge streak penalty — breaks through the 60% Layer2 floor
    # streak²x5: 1->-5, 2->-20, 3->-45, 4->-80
    trend = state.get("coherence_trend", {}) if state else {}
    div_streak = trend.get("diverge_streak", 0)
    if div_streak > 0:
        blended -= div_streak * div_streak * 5

    return max(0, min(100, int(blended)))


def _productivity_bonus(state: dict | None) -> float:
    """Compute bonus points for productive work. Max 8 points.

    Rewards: edits (code changes), productive bash (tests, builds, commits),
    and Agent delegation (sub-agent work).
    """
    if not state:
        return 0.0

    bonus = 0.0

    # Edit count: each edit is a sign of progress (cap at 4 pts)
    edits = state.get("edit_count", 0)
    bonus += min(4, edits * 1.0)

    # Productive commands in progress window (cap at 3 pts)
    progress = state.get("progress_window", [])
    productive = sum(1 for e in progress if e.get("productive"))
    bonus += min(3, productive * 1.0)

    # Agent delegation: using sub-agents is healthy workflow (cap at 1 pt)
    recent_tools = state.get("recent_tools", [])
    agent_calls = sum(1 for t in recent_tools if t == "Agent")
    bonus += min(1, agent_calls * 1.0)

    return min(8.0, bonus)


# ---------------------------------------------------------------------------
# Confidence ramp — ignore early, stricter over time
# ---------------------------------------------------------------------------


def _confidence_multiplier(turn: int) -> float:
    """Returns a multiplier for threshold sensitivity. Higher = stricter.

    Note: Layer 3 triggers at turn 10, so the ramp must allow suggestions by then.
    The 'too early' cutoff (conf < 0.5) only applies to turns < 10.
    """
    if turn < 10:
        return 0.3  # suppress — too early
    if turn < 20:
        return 0.6  # moderate
    if turn <= 40:
        return 1.0  # normal
    return 1.3  # strict — long sessions are more prone to drift


# ---------------------------------------------------------------------------
# Layer 3: LLM + Embedding semantic analysis
# ---------------------------------------------------------------------------


def _maybe_trigger_layer3(state: dict, session_id: str) -> None:
    turn = state.get("turn_count", 0)
    last_llm = state.get("last_llm_turn", 0)
    composite = state.get("composite_score", 100)

    if turn - last_llm < _LLM_COOLDOWN:
        return

    # Adaptive frequency: skip early, more frequent when degraded
    if turn < 10:
        return
    should_trigger = (turn % _LLM_PERIOD == 0) or (composite < 60 and turn > 15)
    if not should_trigger:
        return

    prompts = state.get("recent_user_prompts", [])
    if len(prompts) < 3:
        return

    # Layer 3b: Embedding (synchronous, fast) — pass state for trend tracking
    embed_score = _compute_embed_coherence(prompts, state)
    if embed_score is not None:
        state["embed_coherence_score"] = embed_score

    # Layer 3a: LLM (background, async)
    _run_llm_coherence_check(session_id, prompts)

    state["last_llm_turn"] = turn


def _compute_embed_coherence(prompts: list[str], state: dict | None = None) -> float | None:
    """Embed prompts via oMLX, compute baseline coherence + progressive trend adjustment.

    Baseline: similarity between latest prompt (N) and each prior prompt (N-b),
    where b = 1..min(len-1, 5). This anchors the score to the latest context.

    Progressive trend: if recent distances are shrinking (converging), apply an
    escalating bonus; if expanding (diverging), apply an escalating penalty.
    The further the trend continues, the stronger the adjustment.
    """
    try:
        data = json.dumps({"model": _EMBED_MODEL, "input": prompts}).encode()
        req = urllib.request.Request(  # noqa: S310
            _OMLX_URL,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=_EMBED_TIMEOUT)  # noqa: S310
        result = json.loads(resp.read())
        vecs = [d["embedding"] for d in sorted(result["data"], key=lambda x: x["index"])]
    except Exception:
        return None

    if len(vecs) < 2:
        return None

    # Baseline: similarity of latest prompt (N) vs each prior (N-b), b=1..5
    latest = vecs[-1]
    max_b = min(len(vecs) - 1, 5)
    sims = []  # sims[0] = sim(N, N-1), sims[1] = sim(N, N-2), ...
    for b in range(1, max_b + 1):
        sims.append(_cosine_sim(latest, vecs[-1 - b]))

    # Baseline score: weighted average — closer prompts matter more
    # Weights: b=1 gets 5, b=2 gets 4, ..., b=5 gets 1
    weights = list(range(max_b, 0, -1))  # [5,4,3,2,1] for max_b=5
    weighted_sim = sum(s * w for s, w in zip(sims, weights, strict=False))
    total_weight = sum(weights)
    baseline_sim = weighted_sim / total_weight if total_weight else 0
    baseline = max(0.0, min(100.0, (baseline_sim - 0.3) / 0.5 * 100))

    # Progressive trend: compare consecutive sim deltas
    # delta[i] = sims[i] - sims[i+1] → positive means N-b is MORE similar than N-(b+1)
    # i.e., recent prompts are closer → converging
    if len(sims) >= 2:
        deltas = [sims[i] - sims[i + 1] for i in range(len(sims) - 1)]
        # Count consecutive converging/diverging steps from the most recent
        converge_streak = 0
        diverge_streak = 0
        for d in deltas:
            if d > 0.02:  # converging (recent more similar)
                converge_streak += 1
            elif d < -0.02:  # diverging (recent less similar)
                diverge_streak += 1
            else:
                break  # streak broken

        # Escalating adjustment: triangular number x multiplier
        # Diverge penalty is 2.5x the converge bonus -- punish harder
        if converge_streak > 0:
            trend_adj = sum(range(1, converge_streak + 1)) * 3.0  # +3, +9, +18, +30
        elif diverge_streak > 0:
            trend_adj = -sum(range(1, diverge_streak + 1)) * 8.0  # -8, -24, -48, -80
        else:
            trend_adj = 0.0

        # Store trend info for statusline / debugging
        if state is not None:
            state["coherence_trend"] = {
                "sims": [round(s, 3) for s in sims],
                "converge_streak": converge_streak,
                "diverge_streak": diverge_streak,
                "trend_adj": round(trend_adj, 1),
            }
    else:
        trend_adj = 0.0

    return max(0.0, min(100.0, baseline + trend_adj))


def _cosine_sim(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    mag_a = sum(x * x for x in a) ** 0.5
    mag_b = sum(x * x for x in b) ** 0.5
    return dot / (mag_a * mag_b) if mag_a and mag_b else 0.0


def _run_llm_coherence_check(session_id: str, prompts: list[str]) -> None:
    """Fire-and-forget: background RLM call to analyze prompt coherence."""
    import threading

    threading.Thread(
        target=_run_llm_coherence_impl,
        args=(session_id, prompts),
        daemon=True,
    ).start()


def _run_llm_coherence_impl(session_id: str, prompts: list[str]) -> None:
    """RLM-powered coherence analysis (runs in background thread)."""
    prompt_text = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(prompts))
    analysis = (
        f"以下是同一個 Claude Code session 的最近 {len(prompts)} 個使用者輸入:\n\n"
        f"{prompt_text}\n\n"
        "請評估這些輸入之間的主題連貫性:\n"
        "- 100 = 完全聚焦同一任務\n"
        "- 70-99 = 合理的任務演化(同專案不同面向)\n"
        "- 40-69 = 主題開始分散\n"
        "- 0-39 = 完全無關, 應建議開新 session\n\n"
        '只回傳 JSON: {"score": <number>, "reason": "<一句話>"}'
    )

    result_path = f"{_LLM_PREFIX}-{session_id}.json"

    try:
        from src.shared.rlm_engine import RLMConfig, RLMEngine

        engine = RLMEngine(
            RLMConfig(
                model="grok-4-fast",
                max_iterations=3,
                max_timeout_secs=30,
                api_base="http://localhost:4000/v1",
                api_key="sk-litellm-local-dev",
            )
        )
        result = engine.completion(prompt=analysis, context=prompt_text)
        if result.status == "ok" and result.response:
            _atomic_write(result_path, result.response)
        else:
            _atomic_write(result_path, result.response or "")
    except Exception:  # noqa: S110
        pass


def _consume_llm_result(state: dict, session_id: str) -> None:
    """Read LLM analysis result from file and update state."""
    path = f"{_LLM_PREFIX}-{session_id}.json"
    try:
        raw = Path(path).read_text().strip()
        if not raw:
            return

        # Extract JSON — handle nested braces (e.g., reason containing {})
        # Find the outermost { ... } containing "score"
        json_match = re.search(r'\{[^{}]*"score"\s*:\s*\d+[^{}]*\}', raw)
        if not json_match:
            # Fallback: try to parse the whole thing
            json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            score = data.get("score")
            reason = data.get("reason", "")
            if isinstance(score, (int, float)) and 0 <= score <= 100:
                state["llm_coherence_score"] = float(score)
                state["llm_coherence_reason"] = str(reason)[:200]
                state["layer3_combined_score"] = _compute_layer3_score(state)

    except Exception:  # noqa: S110
        pass


def _compute_layer3_score(state: dict) -> float | None:
    llm = state.get("llm_coherence_score")
    embed = state.get("embed_coherence_score")

    if llm is not None and embed is not None:
        return llm * _LLM_WEIGHT + embed * _EMBED_WEIGHT
    if llm is not None:
        return llm
    if embed is not None:
        return embed
    return None


# ---------------------------------------------------------------------------
# Escalation evaluation
# ---------------------------------------------------------------------------


def _evaluate(state: dict) -> dict | None:
    """Evaluate all layers and return suggestion if needed, or None."""
    ctx_pct = state.get("last_ctx_pct", 0)
    composite = state.get("composite_score", 100)
    layer3 = state.get("layer3_combined_score")
    llm_reason = state.get("llm_coherence_reason", "")
    turn = state.get("turn_count", 0)

    # Confidence ramp: ignore early, stricter over time
    conf = _confidence_multiplier(turn)
    if conf < 0.5:
        return None  # Too early to suggest anything

    drift_active = composite < 60

    # Dynamic thresholds (scaled by inverse confidence — higher conf = lower threshold)
    warn_thr = (_CTX_WARN_DRIFT if drift_active else _CTX_WARN_DEFAULT) / conf
    crit_thr = (_CTX_CRITICAL_DRIFT if drift_active else _CTX_CRITICAL) / conf

    # Token velocity warning: fast growth even if below threshold
    velocity = _compute_ctx_velocity(state)
    velocity_warn = velocity > 5.0 and ctx_pct >= 50  # >5% per turn and already 50%+

    # Build specific diagnostic details
    details = _build_diagnostics(state)

    parts: list[str] = []

    # CRITICAL conditions
    if ctx_pct >= crit_thr:
        parts.append(f"上下文已使用 {ctx_pct:.0f}%")
    if layer3 is not None and layer3 < 40:
        reason_part = f" ({llm_reason})" if llm_reason else ""
        parts.append(f"主題連貫性嚴重下降{reason_part}")
    if composite < 40:
        parts.append(f"工具異常{details}")

    if parts:
        is_topic_drift = layer3 is not None and layer3 < 40
        if is_topic_drift:
            action = (
                "這個 session 涵蓋的主題較廣, context 效率可能下降。"
                "可考慮 /clear 開新 session 聚焦單一主題。"
            )
        else:
            action = "建議執行 /compact 釋放 context 空間。"
        return {
            "level": "critical",
            "text": (
                f"[Context Supervisor] {'; '.join(parts)}。{action}"
                "(請照常回答使用者的問題, 這只是 context 管理建議)"
            ),
        }

    # WARN conditions
    warn_parts: list[str] = []
    if ctx_pct >= warn_thr:
        warn_parts.append(f"Ctx {ctx_pct:.0f}%")
    if velocity_warn:
        warn_parts.append(f"增速 {velocity:.1f}%/turn")
    if layer3 is not None and 40 <= layer3 < 70:
        reason_part = f" ({llm_reason})" if llm_reason else ""
        warn_parts.append(f"主題較分散{reason_part}")
    if 40 <= composite < 60:
        warn_parts.append(f"drift{details}")

    if warn_parts:
        return {
            "level": "warn",
            "text": (
                f"[Context Supervisor] {'; '.join(warn_parts)}。"
                "適時 /compact 可提升回應品質。(照常回答, 這只是背景提醒)"
            ),
        }

    # Drift-only warning
    if drift_active and ctx_pct >= 50:
        return {
            "level": "warn",
            "text": f"[Context Supervisor] 工作模式異常{details}。適時 /compact。（照常回答）",
        }

    return None


def _build_diagnostics(state: dict) -> str:
    """Build short diagnostic string from worst signals."""
    parts = []
    reread = state.get("_worst_reread")
    if reread:
        parts.append(reread)
    cycling = state.get("_worst_cycling")
    if cycling:
        parts.append(cycling)
    if parts:
        return f" [{', '.join(parts)}]"
    return ""


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _extract_session_id(raw_input: str) -> str:
    try:
        parsed = json.loads(raw_input)
        return parsed.get("session_id", "")
    except Exception:
        return ""


def _extract_user_prompt(raw_input: str) -> str:
    try:
        parsed = json.loads(raw_input)
        return parsed.get("prompt", "") or parsed.get("user_prompt", "")
    except Exception:
        return ""


def _state_path(session_id: str) -> str:
    return f"{_STATE_PREFIX}-{session_id}.json"


def _new_state(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "turn_count": 0,
        "edit_count": 0,
        "tool_calls": 0,
        "last_ctx_pct": 0,
        "escalation": "normal",
        "last_suggest_turn": 0,
        "suggest_count": 0,
        "composite_score": 100,
        "recent_tools": [],
        "recent_dirs": [],
        "recent_user_prompts": [],
        "ctx_history": [],
        "file_reads": {},
        "tool_hashes": {},
        "file_mutations": {},
        "bash_commands": [],
        "progress_window": [],
        "scope_violations": [],
        "initial_scope_paths": [],
        "scope_frozen": False,
        "signal_scores": {},
        "llm_coherence_score": None,
        "llm_coherence_reason": "",
        "embed_coherence_score": None,
        "layer3_combined_score": None,
        "last_llm_turn": 0,
        "started_at": time.time(),
    }


def _load_state(session_id: str) -> dict | None:
    try:
        return json.loads(Path(_state_path(session_id)).read_text())
    except Exception:
        return None


def _save_state(session_id: str, state: dict) -> None:
    """Atomic write: write to temp file then rename (prevents partial writes)."""
    try:
        target = _state_path(session_id)
        _atomic_write(target, json.dumps(state, default=str))
    except Exception:  # noqa: S110
        pass


def _atomic_write(path: str, content: str) -> None:
    """Write content to path atomically via tempfile + os.replace."""
    dir_path = os.path.dirname(path) or "/tmp"  # noqa: S108
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except Exception:  # noqa: S110
            pass
        raise


def _canonicalize_input(tool_name: str, tool_input: dict) -> str:
    if tool_name == "Read":
        return tool_input.get("file_path", "")
    if tool_name == "Bash":
        return _normalize_bash(tool_input.get("command", ""))
    if tool_name == "Grep":
        return f"{tool_input.get('pattern', '')}|{tool_input.get('path', '')}"
    if tool_name == "Glob":
        return f"{tool_input.get('pattern', '')}|{tool_input.get('path', '')}"
    if tool_name in ("Write", "Edit"):
        return tool_input.get("file_path", "")
    return json.dumps(tool_input, sort_keys=True)


def _normalize_bash(cmd: str) -> str:
    cmd = cmd.strip()
    cmd = re.sub(r"^(\w+=\S+\s+)+", "", cmd)
    cmd = re.sub(r"\s*[12]?>.*$", "", cmd)
    cmd = re.sub(r"\s+", " ", cmd)
    return cmd.strip()


def _is_productive_cmd(cmd: str) -> bool:
    productive_patterns = [
        "git commit",
        "git push",
        "npm run build",
        "pnpm run build",
        "pytest",
        "ruff",
        "biome",
        "make",
        "cargo build",
        "cargo test",
    ]
    lower = cmd.lower()
    return any(p in lower for p in productive_patterns)


def _in_scope(dir_path: str, scope_paths: list[str]) -> bool:
    shared = ["shared/", "libs/", ".claude/"]
    if any(s in dir_path for s in shared):
        return True
    for sp in scope_paths:
        if dir_path.startswith(sp) or sp.startswith(dir_path):
            return True
    return False
