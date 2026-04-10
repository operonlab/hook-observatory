#!/usr/bin/env python3
"""recall.py — Memvault recall script (autoRecall-enabled).
Triggered by Claude Code UserPromptSubmit hook.
Searches Core API (cascade recall → attitude autoRecall → search fallback)
and returns plain text context.

Helpers (optional, fail-safe):
  recall_dedup.py   — cascade result deduplication (P2)
  recall_cache.py   — local file cache fallback (P1)
  recall_session.py — session context window (P3)

stdin: JSON {"session_id", "prompt", "cwd"}
stdout: Plain text context (or empty for no match)
"""

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Optional helper imports (each can be disabled via env var)
# ---------------------------------------------------------------------------
_dedup_fn = None
_cache_mod = None
_session_fn = None

if os.environ.get("MEMVAULT_RECALL_DEDUP") != "0":
    try:
        from recall_dedup import dedup_cascade
        _dedup_fn = dedup_cascade
    except Exception:
        pass

if os.environ.get("MEMVAULT_RECALL_CACHE") != "0":
    try:
        import recall_cache as _cache_mod
    except Exception:
        pass

if os.environ.get("MEMVAULT_RECALL_SESSION") != "0":
    try:
        from recall_session import extract_session_context
        _session_fn = extract_session_context
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CORE_API_URL = os.environ.get("CORE_API_URL", "http://localhost:10000")
HOME_DIR = str(Path.home())
WORKSHOP_DIR = os.path.join(HOME_DIR, "workshop")

# Match file/dir paths that look like project references.
# Anchored to home/absolute or known project-relative prefixes.
# Intentionally excludes http(s)://, backtick-wrapped tokens, etc.
PATH_PATTERN = re.compile(
    r'(?<![`"\'])'  # not preceded by backtick / quote
    r"(?:"
    r"(?:~/|/Users/\w+/)"  # absolute home paths
    r"|(?:core/src/|stations/|libs/|workbench/src/"
    r"|mcp/|schedules/|bridges/|scripts/)"  # relative project paths
    r")"
    r"[\w/.\-]+"  # path continuation (no spaces)
    r'(?!["\'])'  # not followed by quote
)
SPACE_ID = os.environ.get("MEMVAULT_SPACE_ID", "default")
LOG_DIR = Path.home() / "Claude" / "memvault" / "logs"
LOG_FILE = LOG_DIR / "recall.log"
MAX_PROMPT_LEN = 2000
MAX_OUTPUT_CHARS = 4000
CURL_TIMEOUT = 10
PYTHON = str(Path.home() / ".local" / "bin" / "python3")

# Extend PATH to match shell script behavior
extra_paths = [
    "/opt/homebrew/bin",
    str(Path.home() / ".local" / "bin"),
    "/usr/local/bin",
    "/usr/bin",
    "/bin",
]
current_path = os.environ.get("PATH", "")
os.environ["PATH"] = ":".join(extra_paths + [current_path])

LOG_DIR.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    """Write timestamped log message to log file (silent — no stderr)."""
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[recall] {ts} {msg}"
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def http_get(url: str, timeout: int = 10) -> tuple:
    """GET request, return (status_code, response_body). Returns (0, '') on error."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        return e.code, body
    except Exception:
        return 0, ""


def _should_inject_attitudes(prompt: str) -> bool:
    """Decide whether to inject attitude facts."""
    if len(prompt) < 10:
        return False
    if prompt.startswith("/"):
        return False
    if prompt.startswith("```"):
        return False
    return True


def _format_attitudes(raw_body: str) -> str:
    """Format attitude facts API response into markdown section."""
    try:
        data = json.loads(raw_body)
    except json.JSONDecodeError:
        return ""
    if not isinstance(data, list) or not data:
        return ""

    lines = ["\n\n### 行為提醒"]
    for item in data:
        fact = item.get("fact", "")
        category = item.get("category", "")
        confidence = item.get("confidence", 0)
        if fact:
            lines.append(f"- [{category}] {fact} ({confidence:.2f})")
    return "\n".join(lines) if len(lines) > 1 else ""


def validate_refs(text: str) -> set[str]:
    """Extract file path references from text and return stale (non-existent) ones."""
    refs = PATH_PATTERN.findall(text)
    stale: set[str] = set()
    for ref in refs:
        # Normalize to absolute path
        if ref.startswith("~/"):
            full = os.path.join(HOME_DIR, ref[2:])
        elif ref.startswith("/"):
            full = ref
        else:
            full = os.path.join(WORKSHOP_DIR, ref)
        if not os.path.exists(full):
            stale.add(ref)
    return stale


def main() -> None:
    # Safety net — always exit 0
    try:
        _main()
    except Exception:
        pass
    sys.exit(0)


def _main() -> None:
    # ── Read stdin ────────────────────────────────────────────────────────────
    try:
        raw_input = sys.stdin.read()
        input_data = json.loads(raw_input)
    except Exception:
        log("Failed to parse stdin JSON")
        return

    prompt = input_data.get("prompt", "").strip()
    session_id = input_data.get("session_id", "").strip()

    if not prompt:
        log("No prompt, skipping")
        return

    # ── Skip conditions ───────────────────────────────────────────────────────
    if os.environ.get("MEMVAULT_SKIP_RECALL") == "1":
        log("Skipping — MEMVAULT_SKIP_RECALL=1")
        return

    if prompt.startswith("<"):
        log("Skipping system message")
        return

    if len(prompt) > MAX_PROMPT_LEN:
        log(f"Skipping long prompt ({len(prompt)} chars)")
        return

    cwd = input_data.get("cwd", "").strip()
    log(f"Session: {session_id or 'unknown'} | Prompt: {prompt[:80]}")

    # ── Session Context Window (P3) ──────────────────────────────────────────
    session_context = ""
    if _session_fn and session_id:
        try:
            session_context = _session_fn(session_id, cwd, prompt)
            if session_context:
                log(f"Session context: {len(session_context)} chars")
        except Exception:
            pass

    # ── URL-encode the query ──────────────────────────────────────────────────
    encoded_q = urllib.parse.quote(prompt)

    # ── Primary: Cascade Recall (L2→L1→L0→blocks) ────────────────────────────
    cascade_url = f"{CORE_API_URL}/api/memvault/kg/recall?q={encoded_q}&top_k=5&space_id={SPACE_ID}"
    _, cascade_body = http_get(cascade_url, timeout=CURL_TIMEOUT)

    cache_stale = False
    formatted = ""

    # ── Cache integration (P1) ───────────────────────────────────────────────
    if _cache_mod:
        normalized_q = _cache_mod.normalize_query(prompt)
        q_hash = _cache_mod.query_hash(normalized_q)

    if cascade_body:
        try:
            cascade_data = json.loads(cascade_body)
        except json.JSONDecodeError:
            cascade_data = {}
        # Write to cache on success
        if _cache_mod and cascade_data.get("layers_searched"):
            _cache_mod.write_cache(
                _cache_mod.CASCADE_CACHE_DIR, q_hash, prompt, normalized_q,
                cascade_data, _cache_mod.CASCADE_TTL,
            )
    else:
        cascade_data = {}
        # API failed → try cache fallback
        if _cache_mod:
            log("API failed, trying cache fallback")
            cached, is_stale = _cache_mod.read_cache(
                _cache_mod.CASCADE_CACHE_DIR, q_hash,
                _cache_mod.CASCADE_TTL, _cache_mod.CASCADE_STALE_TTL,
            )
            if cached is None:
                cached, is_stale = _cache_mod.read_latest(
                    _cache_mod.CASCADE_CACHE_DIR, _cache_mod.CASCADE_STALE_TTL,
                )
            if cached:
                cascade_data = cached
                cache_stale = is_stale
                log(f"Cache {'stale ' if is_stale else ''}hit")

    # ── Dedup (P2) ───────────────────────────────────────────────────────────
    if _dedup_fn and cascade_data.get("layers_searched"):
        try:
            cascade_data = _dedup_fn(cascade_data)
            log("Dedup applied")
        except Exception:
            pass

    if cascade_data:
        if "layers_searched" in cascade_data:
            layers_list = cascade_data.get("layers_searched", [])
            layers = ", ".join(layers_list) if layers_list else ""

            if layers:
                formatted = f"## 相關記憶（cascade recall: {layers}）"

                # Summaries (L2 — CommunitySummary, enriched by dedup with community metadata)
                summaries = cascade_data.get("summaries", [])
                if summaries:
                    formatted += "\n\n### 智慧節點"
                    for s in summaries:
                        summary_text = s.get("summary", "")
                        key_findings = s.get("key_findings", [])
                        c_name = s.get("_community_name")
                        c_size = s.get("_community_size", 0)
                        if summary_text:
                            if c_name:
                                formatted += f"\n- **{c_name}** (size: {c_size}): {summary_text}"
                            else:
                                formatted += f"\n- {summary_text}"
                            if key_findings:
                                for kf in key_findings:
                                    formatted += f"\n  - {kf}"

                # Communities (L1)
                communities = cascade_data.get("communities", [])
                if communities:
                    formatted += "\n\n### 知識社群"
                    for c in communities:
                        name = c.get("name", "")
                        size = c.get("size", 0)
                        summary = c.get("summary") or "—"
                        if name:
                            formatted += f"\n- **{name}** (size: {size}): {summary}"

                # Triples (L0)
                triples = cascade_data.get("triples", [])
                stale_refs: set[str] = set()
                if triples:
                    formatted += "\n\n### Triples"
                    for t in triples:
                        subj = t.get("subject", "")
                        pred = t.get("predicate", "")
                        obj = t.get("object", "")
                        if subj:
                            triple_text = f"{subj} --{pred}--> {obj}"
                            triple_stale = validate_refs(triple_text)
                            stale_refs.update(triple_stale)
                            stale_suffix = " [stale ref]" if triple_stale else ""
                            formatted += f"\n- {triple_text}{stale_suffix}"

                # Blocks
                blocks = cascade_data.get("blocks", [])
                if blocks:
                    formatted += "\n\n### Memory Blocks"
                    for b in blocks:
                        topic = b.get("topic") or "untitled"
                        content = (b.get("content") or "—")[:200]
                        tags = b.get("tags", [])
                        tag_str = f" (tags: {', '.join(tags)})" if tags else ""
                        block_text = f"{topic}: {content}{tag_str}"
                        block_stale = validate_refs(block_text)
                        stale_refs.update(block_stale)
                        stale_suffix = " ⚠️ stale" if block_stale else ""
                        formatted += f"\n- **{topic}**: {content}{tag_str}{stale_suffix}"

                # Log and append stale refs warning
                for ref in stale_refs:
                    log(f"Stale ref: {ref}")

                summary_count = len(summaries)
                community_count = len(communities)
                triple_count = len(triples)
                block_count = len(blocks)
                log(
                    f"Cascade recall: {layers} "
                    f"({summary_count} summaries, {community_count} communities, "
                    f"{triple_count} triples, {block_count} blocks)"
                )

                # Skill Profile context injection
                skill_tags = set()
                for t in triples:
                    # Check triple tags if available
                    for tag in t.get("tags", []):
                        if tag.startswith("skill:"):
                            skill_tags.add(tag[6:])
                # Also check subject/predicate for skill references
                for t in triples:
                    subj = t.get("subject", "").lower()
                    pred = t.get("predicate", "").lower()
                    if "skill" in pred or "使用" in pred:
                        skill_tags.add(t.get("subject", ""))

                if skill_tags:
                    skill_section = ""
                    for skill_name in list(skill_tags)[:3]:
                        encoded_skill = urllib.parse.quote(skill_name)
                        sp_url = (
                            f"{CORE_API_URL}/api/memvault/kg/skill-profiles/{encoded_skill}"
                            f"?space_id={SPACE_ID}"
                        )
                        sp_status, sp_body = http_get(sp_url, timeout=3)
                        if sp_status == 200 and sp_body:
                            try:
                                profile = json.loads(sp_body)
                                level_zh = {
                                    "novice": "新手",
                                    "proficient": "熟練",
                                    "expert": "專家",
                                }
                                level = level_zh.get(
                                    profile.get("proficiency_level", ""),
                                    profile.get("proficiency_level", ""),
                                )
                                sr_pct = profile.get("success_rate", 0) * 100
                                skill_section += (
                                    f"\n- **{skill_name}**: {profile.get('total_uses', 0)} 次使用, "
                                    f"{sr_pct:.0f}% 成功率 ({level})"
                                )
                            except (json.JSONDecodeError, KeyError):
                                pass
                    if skill_section:
                        formatted += f"\n\n### Skill 熟練度{skill_section}"
                        log(f"Skill profile injected: {list(skill_tags)[:3]}")

                # Stale refs summary (cascade path)
                if stale_refs:
                    formatted += (
                        f"\n\n⚠️ {len(stale_refs)} 個記憶參照的檔案已不存在，建議驗證後再行動"
                    )

    # ── Fallback: simple search if cascade returned nothing ───────────────────
    if not formatted:
        search_url = f"{CORE_API_URL}/api/memvault/search?q={encoded_q}&top_k=5&space_id={SPACE_ID}"
        _, search_body = http_get(search_url, timeout=CURL_TIMEOUT)

        if search_body:
            try:
                search_data = json.loads(search_body)
            except json.JSONDecodeError:
                search_data = []

            if isinstance(search_data, list) and search_data:
                result_count = len(search_data)
                formatted = f"## 相關記憶（search: {result_count} results）"
                search_stale_refs: set[str] = set()
                for item in search_data:
                    block = item.get("block", {}) if isinstance(item, dict) else {}
                    topic = block.get("topic") or "untitled"
                    content = (block.get("content") or "—")[:200]
                    tags = block.get("tags", [])
                    tag_str = f" (tags: {', '.join(tags)})" if tags else ""
                    block_text = f"{topic}: {content}{tag_str}"
                    block_stale = validate_refs(block_text)
                    search_stale_refs.update(block_stale)
                    stale_suffix = " ⚠️ stale" if block_stale else ""
                    formatted += f"\n- **{topic}**: {content}{tag_str}{stale_suffix}"
                for ref in search_stale_refs:
                    log(f"Stale ref: {ref}")
                if search_stale_refs:
                    formatted += (
                        f"\n\n⚠️ {len(search_stale_refs)} 個記憶參照的檔案已不存在，建議驗證後再行動"
                    )
                log(f"Search fallback: {result_count} results")

    # ── Step 2: Attitude autoRecall ──────────────────────────────────────────
    if _should_inject_attitudes(prompt):
        att_url = (
            f"{CORE_API_URL}/api/memvault/kg/attitudes/relevant"
            f"?q={encoded_q}&top_k=3&space_id={SPACE_ID}"
        )
        _, att_body = http_get(att_url, timeout=3)
        att_from_cache = False
        if not att_body and _cache_mod:
            att_hash = _cache_mod.query_hash(_cache_mod.normalize_query(prompt))
            cached_att, _ = _cache_mod.read_cache(
                _cache_mod.ATTITUDE_CACHE_DIR, att_hash,
                _cache_mod.ATTITUDE_TTL, _cache_mod.ATTITUDE_STALE_TTL,
            )
            if cached_att:
                att_body = json.dumps(cached_att)
                att_from_cache = True
        if att_body:
            att_section = _format_attitudes(att_body)
            if att_section:
                formatted += att_section
                log("Attitude autoRecall injected" + (" (cache)" if att_from_cache else ""))
            # Cache successful attitude response
            if _cache_mod and not att_from_cache:
                try:
                    att_data = json.loads(att_body)
                    if isinstance(att_data, list) and att_data:
                        att_hash = _cache_mod.query_hash(_cache_mod.normalize_query(prompt))
                        _cache_mod.write_cache(
                            _cache_mod.ATTITUDE_CACHE_DIR, att_hash, prompt,
                            _cache_mod.normalize_query(prompt), att_data,
                            _cache_mod.ATTITUDE_TTL,
                        )
                except Exception:
                    pass

    # ── No results ────────────────────────────────────────────────────────────
    if not formatted and not session_context:
        log("No results from API")
        return

    # ── Assemble output ──────────────────────────────────────────────────────
    output_parts = []
    if session_context:
        output_parts.append(session_context)
    if formatted:
        output_parts.append(formatted)

    # Stale cache warning
    if cache_stale:
        output_parts.append("\n> ⚠️ 此記憶來自快取（可能已過時），Core API 暫時無法連線")

    full_output = "\n\n".join(output_parts)

    # ── Token budget cap ─────────────────────────────────────────────────────
    if len(full_output) > MAX_OUTPUT_CHARS:
        full_output = full_output[:MAX_OUTPUT_CHARS]
        log(f"Output truncated to {MAX_OUTPUT_CHARS} chars")

    print(full_output)

    # ── Skill suggestion ──────────────────────────────────────────────────────
    triggers_file = Path.home() / ".claude" / "data" / "skill-index" / "triggers.json"
    if triggers_file.is_file():
        try:
            triggers_data = json.loads(triggers_file.read_text(encoding="utf-8"))
            prompt_lower = prompt.lower()
            matches = [
                s["name"]
                for s in triggers_data
                if any(t.lower() in prompt_lower for t in s.get("triggers", []))
            ]
            if matches:
                skill_list = ", ".join(matches[:3])
                print("")
                print(f"建議使用的 Skills: {skill_list}")
                log(f"Skill suggestions: {skill_list}")
        except Exception:
            pass

    log("Done")


if __name__ == "__main__":
    main()
