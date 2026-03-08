#!/usr/bin/env python3
"""Memvault — extraction pipeline with Core API backend.
Same dual-LLM extraction as V1, but writes to PostgreSQL via memvault Core API
instead of markdown files.

Pipeline: transcript → LLM extraction → refinement → Core API POST
Fallback: if Core API is unreachable, falls back to JSONL file writing.

stdin: JSON {"session_id", "transcript_path", "cwd"}
"""

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# 0. Configuration & logging
# ---------------------------------------------------------------------------
LOG_DIR = Path.home() / "Claude" / "memvault" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "extract-v2.log"
FALLBACK_DIR = Path.home() / "Claude" / "memvault" / "extractions"

MEMVAULT_API_URL = os.environ.get("MEMVAULT_API_URL", "http://localhost:8801")
MEMVAULT_SPACE_ID = os.environ.get("MEMVAULT_SPACE_ID", "default")


def log(msg: str) -> None:
    """Write timestamped log message to stderr and log file."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[memvault] {msg}"
    print(line, file=sys.stderr)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def log_separator() -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep = f"\n[memvault] ====== {ts} ======"
    print(sep, file=sys.stderr)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(sep + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 1. Read stdin JSON and extract fields
# ---------------------------------------------------------------------------
def main() -> None:
    log_separator()

    try:
        input_json = json.loads(sys.stdin.read())
    except json.JSONDecodeError as e:
        log(f"Invalid JSON input: {e}")
        sys.exit(0)

    session_id = input_json.get("session_id", "").strip()
    transcript_path = input_json.get("transcript_path", "").strip()
    cwd = input_json.get("cwd", "").strip()

    if not session_id or not transcript_path:
        log("Missing session_id or transcript_path, skipping.")
        sys.exit(0)

    transcript = Path(transcript_path)
    if not transcript.is_file():
        log(f"Transcript file not found: {transcript_path}")
        sys.exit(0)

    log(f"Processing session {session_id} ...")

    # ---------------------------------------------------------------------------
    # 2. Read JSONL transcript, filter user/assistant messages
    # ---------------------------------------------------------------------------
    conversation_lines = []
    try:
        with open(transcript, encoding="utf-8") as f:
            for raw_line in f:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    entry = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue

                entry_type = entry.get("type", "")
                if entry_type not in ("user", "assistant"):
                    continue

                message = entry.get("message", {})
                content = message.get("content", "")
                text = ""
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    parts = []
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            parts.append(item.get("text", ""))
                    text = "\n".join(parts)

                if text:
                    role = "USER" if entry_type == "user" else "ASSISTANT"
                    conversation_lines.append(f"{role}: {text}")
    except Exception as e:
        log(f"Error reading transcript: {e}")
        sys.exit(0)

    conversation = "\n".join(conversation_lines)
    if not conversation:
        log("No conversation content found, skipping.")
        sys.exit(0)

    # ---------------------------------------------------------------------------
    # 3. Count message pairs — skip if fewer than 3 exchanges
    # ---------------------------------------------------------------------------
    user_count = sum(1 for line in conversation_lines if line.startswith("USER: "))
    assistant_count = sum(1 for line in conversation_lines if line.startswith("ASSISTANT: "))

    if user_count < 3 or assistant_count < 3:
        pair_count = min(user_count, assistant_count)
        log(f"Only {pair_count} exchange(s), skipping (need >= 3).")
        sys.exit(0)

    log(f"Found {user_count} user + {assistant_count} assistant messages.")

    # ---------------------------------------------------------------------------
    # 4. Truncate conversation to last ~30000 chars
    # ---------------------------------------------------------------------------
    conv_len = len(conversation)
    if conv_len > 30000:
        conversation = conversation[-30000:]
        # Drop potentially partial first line
        newline_pos = conversation.find("\n")
        if newline_pos != -1:
            conversation = conversation[newline_pos + 1 :]
        log(f"Truncated conversation from {conv_len} to ~30000 chars.")

    # ---------------------------------------------------------------------------
    # 5. Build extraction prompt and call LLM
    # ---------------------------------------------------------------------------
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    prompt = f"""你是對話記憶提煉專家。分析以下 Claude Code 對話 transcript，提取值得長期記住的資訊。

只提取以下類型（按重要性排序）：
1. 失敗的方法 — 嘗試了什麼但沒成功，為什麼
2. 使用者修正 — 使用者糾正了 AI 的什麼錯誤
3. 決策記錄 — 為什麼選了 A 而不是 B
4. 溝通偏好 — 使用者的語言習慣、偏好
5. 技術洞察 — workaround、gotcha、best practice
6. 共同成果 — 一起完成了什麼重要的事
7. 最近關注 — 使用者最近在研究或關心什麼

忽略：簡單檔案讀寫、常規 git 操作、trivial 問答。

如果沒有值得記住的內容，只回傳 "SKIP"（不要加其他文字）。

否則，用以下格式回傳（嚴格遵守，每個欄位一行）：
## Session: {session_id} ({timestamp})
**Topic**: [簡短主題，10字以內]
**Type**: [只選一個最主要的: failed-approach | user-correction | decision | communication | technical | achievement | recent-focus]
**Tags**: [3-8 個小寫標籤，逗號分隔。包括工具名、技術名、概念名。例如: react, zustand, safari-bug, css-grid。禁止使用過於泛泛的單詞標籤如: ai, technical, design, code, tool, system, project, workflow — 必須用複合標籤如: ai-memory, technical-insight, css-design, cli-tool]
**Project**: {cwd}

- [記憶點 1]
- [記憶點 2]
- [記憶點 N]

**Attitudes**: [使用者表達的偏好/信念/原則，格式 category|fact，0-5 條]
  - category 只限: tool_behavior | config | architecture | workflow | preference | technical | naming | syntax | performance
  - 只提取有明確證據的態度，不猜測。沒有就留空

---

以下是對話 transcript：

{conversation}"""

    # Prevent recall from firing on our internal LLM calls
    env = os.environ.copy()
    env["MEMVAULT_SKIP_RECALL"] = "1"

    memvault_llm = os.environ.get("MEMVAULT_LLM", "gemini")
    memvault_model = os.environ.get("MEMVAULT_MODEL", "")

    if memvault_llm == "gemini":
        if not memvault_model:
            memvault_model = "gemini-2.5-pro"
    elif memvault_llm == "claude":
        if not memvault_model:
            memvault_model = "haiku"
    elif memvault_llm == "codex":
        pass  # model stays empty unless explicitly set

    log(f"Calling {memvault_llm} ({memvault_model or 'default'}) for extraction ...")

    llm_output = _call_llm(memvault_llm, memvault_model, prompt, env)
    if llm_output is None:
        sys.exit(0)

    # ---------------------------------------------------------------------------
    # 6. Check for SKIP response
    # ---------------------------------------------------------------------------
    trimmed = llm_output.strip()
    if trimmed == "SKIP":
        log("LLM returned SKIP — nothing worth remembering.")
        sys.exit(0)

    if not trimmed:
        log("LLM returned empty response, skipping.")
        sys.exit(0)

    # ---------------------------------------------------------------------------
    # 6.5. Refinement pass
    # ---------------------------------------------------------------------------
    memvault_refine = os.environ.get("MEMVAULT_REFINE", "1")
    memvault_refine_model = os.environ.get("MEMVAULT_REFINE_MODEL", "sonnet")

    if memvault_refine == "1":
        log(f"Refinement pass: calling Claude ({memvault_refine_model}) ...")

        refine_prompt = f"""你是記憶品質審查員。以下是從 Claude Code 對話中提煉的記憶草稿。
請審查並改善品質，然後輸出最終版本。

## 審查規則

1. **格式驗證** — 確保有且僅有以下欄位：## Session, **Topic**, **Type**, **Tags**, **Project**, bullet points, 以及可選的 **Attitudes**
2. **Type 正規化** — 只允許一個值：failed-approach | user-correction | decision | communication | technical | achievement | recent-focus
3. **Tags 品質** — 3-8 個小寫標籤，禁止泛泛單詞（ai, technical, design, code, tool, system, project, workflow），必須用複合標籤（ai-memory, css-design, cli-tool）
4. **記憶點品質** — 每條必須具體可操作，刪除空泛的（如「偏好使用繁體中文」若已是已知事實）
5. **去重** — 合併重複或高度相似的記憶點
6. **精簡** — 總記憶點控制在 3-7 條，寧精不濫
7. **Attitudes 驗證** — category 必須在以下 9 個枚舉值中：tool_behavior, config, architecture, workflow, preference, technical, naming, syntax, performance。刪除不確定或猜測性態度，刪除 category 不在枚舉中的條目

## 輸出格式

如果審查後認為記憶完全不值得保留，只回傳 "SKIP"。

否則直接輸出修正後的完整記憶（不要加解釋、不要加 code fence）：
## Session: ...
**Topic**: ...
**Type**: ...
**Tags**: ...
**Project**: ...

- ...

**Attitudes**: (可選，0-5 條，格式: category|fact)
  - category|fact

## 待審查的記憶草稿

{trimmed}"""

        refined_output = _call_llm("claude", memvault_refine_model, refine_prompt, env)

        if refined_output is None:
            log("Refinement call failed, using raw extraction.")
        else:
            refined_trimmed = refined_output.strip()
            refined_first_line = refined_trimmed.split("\n")[0].strip() if refined_trimmed else ""

            if refined_first_line == "SKIP":
                log("Refinement returned SKIP — judged not worth keeping.")
                sys.exit(0)

            if refined_trimmed and "## Session:" in refined_trimmed:
                # Extract from ## Session: onwards
                idx = refined_trimmed.find("## Session:")
                refined_block = refined_trimmed[idx:] if idx != -1 else ""
                if refined_block:
                    log("Refinement accepted — using refined output.")
                    trimmed = refined_block
                else:
                    log("Refinement block extraction failed, using raw extraction.")
            else:
                log("Refinement output invalid, using raw extraction.")

    # ---------------------------------------------------------------------------
    # 7. Clean output — strip LLM artifacts
    # ---------------------------------------------------------------------------
    clean_lines = []
    for line in trimmed.splitlines():
        if line.startswith("Created execution plan for "):
            continue
        if line.startswith("Expanding hook command:"):
            continue
        if line.startswith("Hook execution for "):
            continue
        if line.startswith("```"):
            continue
        # Clean up Type field: strip pipe-separated suffix
        line = re.sub(r"^(\*\*Type\*\*: [a-zA-Z-]+) \|.*", r"\1", line)
        clean_lines.append(line)
    clean_output = "\n".join(clean_lines)

    # ---------------------------------------------------------------------------
    # 7.5. Extract attitudes and POST to Core API
    # ---------------------------------------------------------------------------
    valid_categories = {
        "tool_behavior",
        "config",
        "architecture",
        "workflow",
        "preference",
        "technical",
        "naming",
        "syntax",
        "performance",
    }

    attitude_lines = _extract_attitudes(clean_output)
    attitude_count = 0
    for line in attitude_lines:
        parts = line.split("|", 1)
        if len(parts) != 2:
            continue
        attitude_category = parts[0].strip()
        attitude_fact = parts[1].strip()

        if attitude_category not in valid_categories:
            log(f"Attitude skipped — invalid category: {attitude_category}")
            continue

        if not attitude_fact:
            continue

        attitude_payload = json.dumps(
            {
                "fact": attitude_fact,
                "category": attitude_category,
                "source_session": session_id,
            }
        ).encode("utf-8")

        try:
            req = urllib.request.Request(
                f"{MEMVAULT_API_URL}/api/memvault/kg/attitudes/evolve?space_id={MEMVAULT_SPACE_ID}",
                data=attitude_payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass  # non-critical

        attitude_count += 1
        log(f"Attitude evolve: [{attitude_category}] {attitude_fact}")

    if attitude_count:
        log(f"{attitude_count} attitude(s) sent to Core API.")

    # ---------------------------------------------------------------------------
    # 8. Parse LLM output into structured fields
    # ---------------------------------------------------------------------------
    entry_topic = ""
    entry_type = ""
    entry_tags = ""
    entry_project = ""

    for line in clean_output.splitlines():
        if line.startswith("**Topic**: ") and not entry_topic:
            entry_topic = line[len("**Topic**: ") :].strip()
        elif line.startswith("**Type**: ") and not entry_type:
            entry_type = line[len("**Type**: ") :].strip()
        elif line.startswith("**Tags**: ") and not entry_tags:
            entry_tags = line[len("**Tags**: ") :].strip()
        elif line.startswith("**Project**: ") and not entry_project:
            entry_project = line[len("**Project**: ") :].strip()

    # Extract content: bullet points before Attitudes block
    entry_content = _extract_content(clean_output)
    if not entry_content:
        # fallback: full block from ## Session:
        idx = clean_output.find("## Session:")
        if idx != -1:
            entry_content = clean_output[idx:]

    if not entry_topic or not entry_content:
        log("Failed to parse LLM output — missing topic or content, skipping.")
        sys.exit(0)

    # Map types to V2 block_type enum
    type_map = {
        "failed-approach": "technical",
        "technical": "technical",
        "user-correction": "preference",
        "communication": "preference",
        "decision": "decision",
        "achievement": "insight",
        "recent-focus": "insight",
        "insight": "insight",
        "pattern": "pattern",
    }
    v2_type = type_map.get(entry_type, "technical")

    # Build tags JSON array
    tags_list = [t.strip() for t in entry_tags.split(",") if t.strip()]

    log(f"Parsed: topic='{entry_topic}' type={entry_type} -> {v2_type} tags={entry_tags}")

    # ---------------------------------------------------------------------------
    # 9. POST to Core API (with V1 fallback)
    # ---------------------------------------------------------------------------
    payload = json.dumps(
        {
            "topic": entry_topic,
            "content": entry_content,
            "block_type": v2_type,
            "session_id": session_id,
            "project": entry_project or cwd,
            "tags": tags_list,
            "source": "session_end",
        }
    ).encode("utf-8")

    http_code, response_body = _http_post(
        f"{MEMVAULT_API_URL}/api/memvault/blocks?space_id={MEMVAULT_SPACE_ID}",
        payload,
        timeout=10,
        connect_timeout=3,
    )

    if http_code == 201:
        try:
            resp_data = json.loads(response_body)
            block_id = resp_data.get("id", "")
        except Exception:
            block_id = ""
        log(f"Block created via Core API (id={block_id}).")

        # Sync tags in background (non-critical)
        try:
            req = urllib.request.Request(
                f"{MEMVAULT_API_URL}/api/memvault/tags/sync?space_id={MEMVAULT_SPACE_ID}",
                data=b"",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass

        log("Done (via Core API).")
        sys.exit(0)

    # ---------------------------------------------------------------------------
    # 10. Core API failed — fallback to JSONL file
    # ---------------------------------------------------------------------------
    log(f"Core API returned HTTP {http_code}, falling back to JSONL.")
    if response_body:
        try:
            err_data = json.loads(response_body)
            api_error = err_data.get("detail") or err_data.get("message", "")
            if api_error:
                log(f"API error: {api_error}")
        except Exception:
            pass

    year_month = datetime.now().strftime("%Y-%m")
    today = datetime.now().strftime("%Y-%m-%d")
    fallback_file = FALLBACK_DIR / year_month / f"{today}.jsonl"
    fallback_file.parent.mkdir(parents=True, exist_ok=True)

    # Dedup check
    if fallback_file.is_file():
        try:
            content = fallback_file.read_text(encoding="utf-8")
            if f'"session_id":"{session_id}"' in content:
                log(f"Session {session_id} already in fallback JSONL, skipping.")
                sys.exit(0)
        except Exception:
            pass

    fallback_entry = json.dumps(
        {
            "session_id": session_id,
            "topic": entry_topic,
            "content": entry_content,
            "block_type": v2_type,
            "project": entry_project or cwd,
            "tags": tags_list,
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "session_end",
            "ingested": False,
        }
    )

    try:
        with open(fallback_file, "a", encoding="utf-8") as f:
            f.write(fallback_entry + "\n")
        log(f"Fallback: extraction saved to {fallback_file}")
        log("Done (JSONL fallback).")
    except Exception as e:
        log(f"Failed to write fallback JSONL: {e}")

    sys.exit(0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _call_llm(llm: str, model: str, prompt: str, env: dict) -> "str | None":
    """Call LLM and return output string, or None on failure."""
    if llm == "gemini":
        cmd = ["gemini", "-m", model, "-p", "按照以下指示分析對話並提煉記憶："]
        return _run_cmd(cmd, input_text=prompt, env=env, label="Gemini")
    elif llm == "claude":
        cmd = ["claude", "-p", "--model", model]
        return _run_cmd(cmd, input_text=prompt, env=env, label="Claude")
    elif llm == "codex":
        codex_args = ["codex", "exec", "--skip-git-repo-check"]
        if model:
            codex_args += ["-m", model]
        return _run_cmd(codex_args, input_text=prompt, env=env, label="Codex")
    else:
        log(f"Unknown LLM: {llm}, skipping.")
        return None


def _run_cmd(cmd: list, input_text: str, env: dict, label: str) -> "str | None":
    """Run subprocess, return stdout or None on error."""
    try:
        result = subprocess.run(
            cmd,
            input=input_text,
            capture_output=True,
            text=True,
            env=env,
            timeout=300,
        )
        if result.returncode != 0:
            log(f"{label} call failed (exit {result.returncode}), skipping.")
            return None
        return result.stdout
    except FileNotFoundError:
        log(f"{label} not found in PATH, skipping.")
        return None
    except subprocess.TimeoutExpired:
        log(f"{label} call timed out, skipping.")
        return None
    except Exception as e:
        log(f"{label} call error: {e}, skipping.")
        return None


def _http_post(url: str, data: bytes, timeout: int = 10, connect_timeout: int = 3) -> tuple:
    """POST request, return (http_code, response_body). Returns (0, '') on error."""
    try:
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
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


def _extract_attitudes(text: str) -> list:
    """Extract attitude bullet lines from the Attitudes section."""
    lines = text.splitlines()
    in_attitudes = False
    attitude_lines = []
    for line in lines:
        if line.startswith("**Attitudes**:"):
            in_attitudes = True
            continue
        if in_attitudes:
            # Stop at next field or section marker
            stripped = line.strip()
            if stripped.startswith("**") and not stripped.startswith("**Attitudes"):
                break
            if stripped.startswith("---") or stripped.startswith("## "):
                break
            if stripped.startswith("- "):
                attitude_lines.append(stripped[2:])
    return attitude_lines


def _extract_content(text: str) -> str:
    """Extract bullet-point content, excluding Attitudes block and trailing ---."""
    lines = text.splitlines()
    content_lines = []
    in_content = False
    for line in lines:
        if line.startswith("- ") and not in_content:
            in_content = True
        if in_content:
            if line.startswith("**Attitudes**:"):
                break
            if line.startswith("---"):
                break
            content_lines.append(line)
    return "\n".join(content_lines)


if __name__ == "__main__":
    main()
