#!/usr/bin/env python3
"""recall_v2.py — Memvault V2 recall script.
Triggered by Claude Code UserPromptSubmit hook.
Searches Core API (cascade recall → search fallback) and returns plain text context.

stdin: JSON {"session_id", "prompt", "cwd"}
stdout: Plain text context (or empty for no match)
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CORE_API_URL = os.environ.get("CORE_API_URL", "http://localhost:8801")
SPACE_ID = os.environ.get("MEMVAULT_SPACE_ID", "default")
LOG_DIR = Path.home() / "Claude" / "memvault" / "logs"
LOG_FILE = LOG_DIR / "recall.log"
MAX_PROMPT_LEN = 2000
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

    log(f"Session: {session_id or 'unknown'} | Prompt: {prompt[:80]}")

    # ── URL-encode the query ──────────────────────────────────────────────────
    encoded_q = urllib.parse.quote(prompt)

    # ── Primary: Cascade Recall (L2→L1→L0→blocks) ────────────────────────────
    cascade_url = f"{CORE_API_URL}/api/memvault/kg/recall?q={encoded_q}&top_k=5&space_id={SPACE_ID}"
    _, cascade_body = http_get(cascade_url, timeout=CURL_TIMEOUT)

    formatted = ""

    if cascade_body:
        try:
            cascade_data = json.loads(cascade_body)
        except json.JSONDecodeError:
            cascade_data = {}

        if "layers_searched" in cascade_data:
            layers_list = cascade_data.get("layers_searched", [])
            layers = ", ".join(layers_list) if layers_list else ""

            if layers:
                formatted = f"## 相關記憶（cascade recall: {layers}）"

                # Wisdom (L2)
                wisdom = cascade_data.get("wisdom", [])
                if wisdom:
                    formatted += "\n\n### Wisdom"
                    for w in wisdom:
                        wisdom_text = w.get("wisdom", "")
                        confidence = w.get("confidence", "")
                        if wisdom_text:
                            formatted += f"\n- {wisdom_text} (confidence: {confidence})"

                # Clusters (L1)
                clusters = cascade_data.get("clusters", [])
                if clusters:
                    formatted += "\n\n### Clusters"
                    for c in clusters:
                        name = c.get("name", "")
                        size = c.get("size", 0)
                        summary = c.get("summary") or "—"
                        if name:
                            formatted += f"\n- **{name}** (size: {size}): {summary}"

                # Triples (L0)
                triples = cascade_data.get("triples", [])
                if triples:
                    formatted += "\n\n### Triples"
                    for t in triples:
                        subj = t.get("subject", "")
                        pred = t.get("predicate", "")
                        obj = t.get("object", "")
                        if subj:
                            formatted += f"\n- {subj} --{pred}--> {obj}"

                # Blocks
                blocks = cascade_data.get("blocks", [])
                if blocks:
                    formatted += "\n\n### Memory Blocks"
                    for b in blocks:
                        topic = b.get("topic") or "untitled"
                        content = (b.get("content") or "—")[:200]
                        tags = b.get("tags", [])
                        tag_str = f" (tags: {', '.join(tags)})" if tags else ""
                        formatted += f"\n- **{topic}**: {content}{tag_str}"

                wisdom_count = len(wisdom)
                cluster_count = len(clusters)
                triple_count = len(triples)
                block_count = len(blocks)
                log(
                    f"Cascade recall: {layers} ({wisdom_count} wisdom, {cluster_count} clusters, {triple_count} triples, {block_count} blocks)"
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
                for item in search_data:
                    block = item.get("block", {}) if isinstance(item, dict) else {}
                    topic = block.get("topic") or "untitled"
                    content = (block.get("content") or "—")[:200]
                    tags = block.get("tags", [])
                    tag_str = f" (tags: {', '.join(tags)})" if tags else ""
                    formatted += f"\n- **{topic}**: {content}{tag_str}"
                log(f"Search fallback: {result_count} results")

    # ── Step 2: Attitude autoRecall ──────────────────────────────────────────
    if _should_inject_attitudes(prompt):
        att_url = (
            f"{CORE_API_URL}/api/memvault/kg/attitudes/relevant"
            f"?q={encoded_q}&top_k=3&space_id={SPACE_ID}"
        )
        _, att_body = http_get(att_url, timeout=3)
        if att_body:
            att_section = _format_attitudes(att_body)
            if att_section:
                formatted += att_section
                log("Attitude autoRecall injected")

    # ── No results ────────────────────────────────────────────────────────────
    if not formatted:
        log("No results from API")
        return

    # ── Output formatted text ─────────────────────────────────────────────────
    print(formatted)

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
