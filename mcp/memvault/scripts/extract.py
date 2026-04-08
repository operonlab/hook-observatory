#!/usr/bin/env python3
"""Memvault extraction pipeline v2 — JSON multi-block extraction.

Pipeline: transcript → enriched input (thinking+tools+errors) → LLM extraction (JSON)
          → refinement → multi-block POST to Core API
Fallback: if Core API is unreachable, falls back to JSONL file writing.

V2 changes (2026-03-11):
- Input: includes thinking blocks, tool_use, tool_result errors (not just text)
- Truncation: 100K for Gemini (was 30K), 30K for others
- Output: JSON with multi-block extraction (was markdown single-block)
- Fields: search_keywords for BM25 boost, bilingual tags for jieba
- Parsing: reliable JSON parsing (was brittle markdown regex)

stdin: JSON {"session_id", "transcript_path", "cwd"}
"""

import json
import os
import subprocess
import sys
import time
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

MEMVAULT_API_URL = os.environ.get("MEMVAULT_API_URL", "http://localhost:10000")
MEMVAULT_SPACE_ID = os.environ.get("MEMVAULT_SPACE_ID", "default")


def log(msg: str) -> None:
    """Write timestamped log message to stderr and log file."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[memvault] {ts} {msg}"
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
    # 2. Read JSONL transcript — include thinking, text, tool_use, tool_result
    # ---------------------------------------------------------------------------
    conversation_lines = []
    user_count = 0
    assistant_count = 0
    thinking_chars = 0

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

                if entry_type == "user":
                    user_count += 1
                else:
                    assistant_count += 1

                if isinstance(content, str):
                    if content.strip():
                        role = "USER" if entry_type == "user" else "ASSISTANT"
                        conversation_lines.append(f"{role}: {content}")
                elif isinstance(content, list):
                    parts = []
                    for item in content:
                        if not isinstance(item, dict):
                            continue
                        item_type = item.get("type", "")

                        if item_type == "text":
                            text = item.get("text", "")
                            if text.strip():
                                parts.append(text)

                        elif item_type == "thinking":
                            # Thinking blocks are the richest source of reasoning
                            text = item.get("text", "")
                            if text.strip() and len(text) > 50:
                                # Truncate very long thinking blocks to key content
                                if len(text) > 2000:
                                    text = text[:2000] + " [...]"
                                parts.append(f"[THINKING] {text}")
                                thinking_chars += len(text)

                        elif item_type == "tool_use":
                            # Tool use shows what was actually done
                            tool_name = item.get("name", "")
                            tool_input = item.get("input", {})
                            # Keep only the tool name + key params for context
                            if tool_name in ("Read", "Write", "Edit", "Grep", "Glob"):
                                path = tool_input.get("file_path", "") or tool_input.get(
                                    "pattern", ""
                                )
                                if path:
                                    parts.append(f"[TOOL:{tool_name}] {path}")
                            elif tool_name == "Bash":
                                cmd = tool_input.get("command", "")
                                if cmd and len(cmd) < 200:
                                    parts.append(f"[TOOL:Bash] {cmd}")

                        elif item_type == "tool_result":
                            # Only include errors from tool results
                            is_error = item.get("is_error", False)
                            if is_error:
                                text = item.get("content", "")
                                if isinstance(text, str) and text.strip():
                                    parts.append(f"[ERROR] {text[:500]}")

                    if parts:
                        role = "USER" if entry_type == "user" else "ASSISTANT"
                        conversation_lines.append(f"{role}: " + "\n".join(parts))
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
    if user_count < 3 or assistant_count < 3:
        pair_count = min(user_count, assistant_count)
        log(f"Only {pair_count} exchange(s), skipping (need >= 3).")
        sys.exit(0)

    log(
        f"Found {user_count} user + {assistant_count} assistant messages "
        f"(thinking: {thinking_chars:,} chars)."
    )

    # ---------------------------------------------------------------------------
    # 4. Truncate conversation — 100K for Gemini, 30K for others
    # ---------------------------------------------------------------------------
    memvault_llm = os.environ.get("MEMVAULT_LLM", "gemini")
    max_chars = 100_000 if memvault_llm == "gemini" else 30_000

    conv_len = len(conversation)
    if conv_len > max_chars:
        conversation = conversation[-max_chars:]
        # Drop potentially partial first line
        newline_pos = conversation.find("\n")
        if newline_pos != -1:
            conversation = conversation[newline_pos + 1 :]
        log(f"Truncated conversation from {conv_len:,} to ~{max_chars:,} chars.")

    # ---------------------------------------------------------------------------
    # 4.5. Load progressive state (from PreCompact mid-session extractions)
    # ---------------------------------------------------------------------------
    progressive_dir = Path.home() / "Claude" / "memvault" / "progressive"
    progressive_file = progressive_dir / f"{session_id}.json"
    progressive_observations = ""
    progressive_count = 0

    if progressive_file.is_file():
        try:
            prog_state = json.loads(progressive_file.read_text(encoding="utf-8"))
            obs_list = prog_state.get("observations", [])
            progressive_count = prog_state.get("compaction_count", 0)
            if obs_list:
                progressive_observations = "\n".join(f"- {obs}" for obs in obs_list)
                log(
                    f"Loaded {len(obs_list)} progressive observations "
                    f"from {progressive_count} compaction(s)."
                )
        except Exception as e:
            log(f"Failed to load progressive state: {e}")

    # ---------------------------------------------------------------------------
    # 5. Build extraction prompt and call LLM
    # ---------------------------------------------------------------------------
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Progressive prior context injection
    progressive_section = ""
    if progressive_observations:
        progressive_section = f"""
## 先前的中途觀察（來自 {progressive_count} 次壓縮前快照）
以下是 session 進行中已記錄的觀察點。利用這些作為先驗知識：
- 已記錄的重要觀察不需要重複提煉（除非有新的補充）
- 如果某個觀察在後續對話中被推翻或修正，以最新版為準
- 聚焦在這些觀察之外的新發現

{progressive_observations}
"""

    prompt = f"""你是對話記憶提煉專家。分析以下 Claude Code 工作 session transcript，提煉值得長期記住的知識。
{progressive_section}
## 提煉目標（按重要性排序）
1. **失敗與修正** — 嘗試了什麼沒成功？使用者糾正了什麼？為什麼？
2. **架構決策** — 為什麼選 A 不選 B？有什麼 trade-off？
3. **技術洞察** — workaround、gotcha、best practice、具體的檔案路徑和函數名
4. **環境怪癖** — 特定環境/版本/設定的坑（下次會重踩的）
5. **共同成果** — 完成了什麼有意義的功能或修復
6. **使用者偏好** — 工作流程偏好、工具選擇、命名慣例

## 輸入說明
- [THINKING] 標記的段落是 AI 的內部推理，包含最深層的技術分析和決策推理
- [TOOL:*] 標記顯示實際執行的操作和檔案路徑
- [ERROR] 標記顯示遇到的錯誤
- 注意：使用者可能混用中文和英文

## 忽略
- 簡單檔案讀寫、常規 git 操作、trivial 問答
- 重複的 tool call 結果
- AI 自己的反思（除非包含具體技術發現）

## 輸出格式

如果沒有值得記住的內容，只回傳 JSON：{{"skip": true}}

否則回傳 JSON（不加 code fence、不加解釋）：
{{
  "blocks": [
    {{
      "topic": "簡短主題（5-15字）",
      "block_type": "technical | decision | preference | insight | pattern | skill",
      "content": "用完整的自然語句描述。包含因果關係和上下文（為什麼這樣做、遇到什麼問題、怎麼解決）。保留具體的檔案路徑、函數名、版本號、錯誤訊息。",
      "tags": ["具體標籤", "工具名", "模組名"],
      "search_keywords": ["關鍵搜尋詞", "中英文都要", "技術術語原文保留"],
      "importance": 0.7,
      "destination": "MEMORY 或 CLAUDE",
      "attitudes": [
        {{"category": "architecture", "fact": "使用者表達的具體偏好或原則"}}
      ]
    }}
  ]
}}

## 欄位說明

### block_type（只選一個）
- `technical`: 技術 gotcha、workaround、bug fix、實作細節
- `decision`: 架構決策、技術選型、為什麼選 A 不選 B
- `preference`: 使用者的工具偏好、命名慣例、工作流程
- `insight`: 跨領域洞察、模式識別、趨勢觀察
- `pattern`: 反覆出現的問題或解決模式
- `skill`: 使用者展現的具體技能、熟練度、學習過程（如 CLI 進階用法、特定框架深度使用、調優技巧）

### tags（3-12 個）
- 必須包含：涉及的工具名、模組名、語言名（如 python, react, psycopg3, sentinel）
- 中英文都可以（如 "排程", "cronicle", "docker"）
- 禁止泛泛單詞：ai, code, tool, system, project, workflow
- 允許複合標籤：css-grid, docker-healthcheck, session-end-hook

### search_keywords（5-15 個，BM25 專用）
這些詞會被 BM25 + jieba 分詞索引，用於精確關鍵字匹配。只放 content 中沒有的補充搜尋詞：
- 同義詞/別名（content 寫 "OrbStack" → keywords 加 "Docker Desktop 替代品"）
- 中英對照（content 用中文描述 → keywords 加英文術語原文，反之亦然）
- 使用者可能用來搜尋的口語化詞彙（如 "掛掉", "卡住", "炸了"）
- 錯誤訊息的關鍵片段（如 "SyntaxError", "FATAL: terminating connection"）
- 不要重複 content 已有的詞 — BM25 已經會分詞 content

### importance（0.0 - 1.0）
Key Point Analysis 權重 — 這條記憶有多重要？
- **0.9-1.0**: 架構鐵律、反覆犯的錯、環境怪癖（缺了必踩坑）
- **0.7-0.8**: 重要決策、技術洞察、有意義的成果
- **0.5-0.6**: 一般性知識、偏好記錄
- **0.3-0.4**: 邊緣觀察、可能有用但不確定
判斷依據：「同一觀點在對話中被提到/強調幾次？」重複出現 = 高權重

### destination
- `CLAUDE`: 環境怪癖、反覆 gotcha、必要指令慣例 — 缺了 AI 會重複犯錯
- `MEMORY`: 決策記錄、修正、成就、關注 — 按需回憶即可
- 每次萃取最多 1-2 個 CLAUDE block

### attitudes（0-5 條，可選）
- category 限定：tool_behavior | config | architecture | workflow | preference | technical | naming | syntax | performance
- 只提取有明確證據的態度，不猜測

## 重要原則
1. **多 block 萃取**：如果 session 涵蓋多個不同主題，拆成多個 block（1-5 個）。每個 block 聚焦一個主題。
2. **保留具體性**：寧可保留 `embedding.py line 42 的 CAST(:emb AS vector)` 也不要抽象成「修復了 SQL 語法」
3. **語意搜尋友善**：content 用完整自然語句（非碎片條列），因為 dense embedding 模型會理解語意。「因為 psycopg3 的 AsyncSession 在長時間 HTTP 呼叫後會損毀連線」比「psycopg3 AsyncSession 損毀」好得多。
4. **關鍵字搜尋互補**：search_keywords 只放 content 中沒有的補充詞。BM25 已經會分詞 content，keywords 的價值在於加入同義詞、中英對照、口語化搜尋詞。
5. **雙語標註**：tags 和 search_keywords 中英文都要有，因為搜尋可能用任一語言
6. **不要編造**：只提取對話中明確出現的資訊

Session ID: {session_id}
Project: {cwd}
Timestamp: {timestamp}

---

以下是對話 transcript：

{conversation}"""

    # Prevent recall from firing on our internal LLM calls
    env = os.environ.copy()
    env["MEMVAULT_SKIP_RECALL"] = "1"

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
    pipeline_t0 = time.monotonic()

    llm_output, extract_elapsed = _call_llm(memvault_llm, memvault_model, prompt, env)
    log(f"Extraction LLM took {extract_elapsed:.1f}s (input ~{len(prompt):,} chars).")
    if llm_output is None:
        sys.exit(0)

    # ---------------------------------------------------------------------------
    # 6. Parse JSON response — multi-block extraction
    # ---------------------------------------------------------------------------
    trimmed = llm_output.strip()
    if not trimmed:
        log("LLM returned empty response, skipping.")
        sys.exit(0)

    # Strip code fences if present
    if trimmed.startswith("```"):
        lines = trimmed.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        trimmed = "\n".join(lines)

    # Try to find JSON object in the response
    json_start = trimmed.find("{")
    json_end = trimmed.rfind("}") + 1
    if json_start == -1 or json_end <= json_start:
        log("LLM output contains no JSON object, skipping.")
        sys.exit(0)

    try:
        extraction = json.loads(trimmed[json_start:json_end])
    except json.JSONDecodeError as e:
        log(f"Failed to parse LLM JSON output: {e}")
        sys.exit(0)

    # Check for skip
    if extraction.get("skip", False):
        log("LLM returned skip=true — nothing worth remembering.")
        sys.exit(0)

    blocks = extraction.get("blocks", [])
    if not blocks:
        log("No blocks in extraction output, skipping.")
        sys.exit(0)

    log(f"Extracted {len(blocks)} block(s) from session.")

    # ---------------------------------------------------------------------------
    # 6.5. Refinement pass (optional — validates and cleans JSON blocks)
    # ---------------------------------------------------------------------------
    memvault_refine = os.environ.get("MEMVAULT_REFINE", "1")
    memvault_refine_llm = os.environ.get("MEMVAULT_REFINE_LLM", "claude")
    # Default model: sonnet for claude, empty for codex/gemini (uses their default)
    default_refine_model = "sonnet" if memvault_refine_llm == "claude" else ""
    memvault_refine_model = os.environ.get("MEMVAULT_REFINE_MODEL", default_refine_model)

    if memvault_refine == "1" and len(blocks) > 0:
        log(f"Refinement pass: calling {memvault_refine_llm} ({memvault_refine_model}) ...")

        refine_prompt = f"""你是記憶品質審查員。以下是從 Claude Code 對話中提煉的記憶 JSON。
審查並改善品質，輸出修正後的 JSON（不加 code fence、不加解釋）。

## 審查規則
1. **content 具體性** — 刪除空泛的描述（如「使用者偏好繁體中文」若已是已知事實），保留具體的檔案路徑、函數名、錯誤訊息
2. **去重** — 合併高度相似的 block，但保留不同主題的 block
3. **tags 品質** — 3-12 個，禁止泛泛（ai, code, tool, system），必須具體（psycopg3, docker-healthcheck）
4. **search_keywords 品質** — 5-15 個，只放 content 中沒有的補充搜尋詞（同義詞、中英對照、口語化詞彙）
5. **attitudes 驗證** — category 必須是：tool_behavior | config | architecture | workflow | preference | technical | naming | syntax | performance
6. **destination 控制** — CLAUDE 最多 2 個 block，其餘都是 MEMORY
7. **block 數量** — 1-5 個，寧精不濫

如果審查後認為完全不值得保留，回傳：{{"skip": true}}
否則回傳修正後的 JSON（同格式）：{{"blocks": [...]}}

待審查：
{json.dumps(extraction, ensure_ascii=False, indent=2)}"""

        refined_output, refine_elapsed = _call_llm(
            memvault_refine_llm, memvault_refine_model, refine_prompt, env
        )
        log(f"Refinement LLM took {refine_elapsed:.1f}s.")

        if refined_output is not None:
            refined_trimmed = refined_output.strip()
            # Strip code fences
            if refined_trimmed.startswith("```"):
                r_lines = refined_trimmed.splitlines()
                if r_lines[0].startswith("```"):
                    r_lines = r_lines[1:]
                if r_lines and r_lines[-1].strip() == "```":
                    r_lines = r_lines[:-1]
                refined_trimmed = "\n".join(r_lines)

            r_start = refined_trimmed.find("{")
            r_end = refined_trimmed.rfind("}") + 1
            if r_start != -1 and r_end > r_start:
                try:
                    refined_data = json.loads(refined_trimmed[r_start:r_end])
                    if refined_data.get("skip", False):
                        log("Refinement returned skip — judged not worth keeping.")
                        sys.exit(0)
                    refined_blocks = refined_data.get("blocks", [])
                    if refined_blocks:
                        log(f"Refinement accepted — {len(refined_blocks)} block(s).")
                        blocks = refined_blocks
                    else:
                        log("Refinement returned empty blocks, using raw extraction.")
                except json.JSONDecodeError:
                    log("Refinement JSON parse failed, using raw extraction.")
            else:
                log("Refinement output invalid, using raw extraction.")
        else:
            log("Refinement call failed, using raw extraction.")

    # ---------------------------------------------------------------------------
    # 7. Process each block — attitudes, CLAUDE suggestions, POST to API
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
    valid_types = {"technical", "decision", "preference", "insight", "pattern"}

    total_created = 0
    total_attitudes = 0
    total_claude_suggestions = 0

    for i, block in enumerate(blocks):
        topic = (block.get("topic") or "").strip()
        content = (block.get("content") or "").strip()
        block_type = (block.get("block_type") or "technical").strip()
        tags = block.get("tags", [])
        search_keywords = block.get("search_keywords", [])
        importance = block.get("importance", 0.5)
        destination = (block.get("destination") or "MEMORY").strip().upper()
        attitudes = block.get("attitudes", [])

        # Clamp importance to [0.0, 1.0]
        try:
            importance = max(0.0, min(1.0, float(importance)))
        except (TypeError, ValueError):
            importance = 0.5

        if not topic or not content:
            log(f"Block {i}: missing topic or content, skipping.")
            continue

        # Validate block_type
        if block_type not in valid_types:
            block_type = "technical"

        # Ensure tags is a list
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]

        # Build storage content: topic + content + search_keywords
        # (Schema has no topic column — prepend to content for embedding/search)
        storage_content = f"## {topic}\n\n{content}"
        if search_keywords:
            kw_line = "搜尋關鍵詞：" + "、".join(search_keywords)
            storage_content = storage_content + "\n\n" + kw_line

        log(
            f"Block {i}: topic='{topic}' type={block_type} imp={importance:.1f} dest={destination} tags={tags}"
        )

        # --- Attitudes ---
        for att in attitudes:
            if not isinstance(att, dict):
                continue
            att_cat = (att.get("category") or "").strip()
            att_fact = (att.get("fact") or "").strip()
            if att_cat not in valid_categories or not att_fact:
                continue

            att_payload = json.dumps(
                {
                    "fact": att_fact,
                    "category": att_cat,
                    "source_session": session_id,
                }
            ).encode("utf-8")

            try:
                req = urllib.request.Request(
                    f"{MEMVAULT_API_URL}/api/memvault/kg/attitudes/evolve?space_id={MEMVAULT_SPACE_ID}",
                    data=att_payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=10)
                total_attitudes += 1
                log(f"  Attitude: [{att_cat}] {att_fact}")
            except Exception:
                pass

        # --- CLAUDE.md suggestions ---
        if destination == "CLAUDE":
            suggestions = [
                {
                    "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "session_id": session_id,
                    "project": cwd,
                    "suggestion": content,
                    "source_topic": topic,
                    "reviewed": False,
                }
            ]
            _write_claude_staging(suggestions)
            total_claude_suggestions += 1

        # --- POST block to Core API ---
        # Schema: content, block_type, tags, source_session (no topic/project/source)
        # Normalize block_type to canonical KAS types
        type_aliases = {
            "technical": "knowledge",
            "decision": "knowledge",
            "insight": "knowledge",
            "pattern": "knowledge",
            "preference": "attitude",
            "skill": "skill",
        }
        api_block_type = type_aliases.get(block_type, block_type)
        if api_block_type not in {"knowledge", "skill", "attitude", "general"}:
            api_block_type = "knowledge"

        payload = json.dumps(
            {
                "content": storage_content,
                "block_type": api_block_type,
                "tags": tags,
                "source_session": session_id,
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
            log(f"  Block created (id={block_id}).")
            total_created += 1

            # Set confidence (importance) via PATCH — not in Create schema
            if block_id:
                conf_payload = json.dumps({"confidence": importance}).encode("utf-8")
                _http_post(
                    f"{MEMVAULT_API_URL}/api/memvault/blocks/{block_id}?space_id={MEMVAULT_SPACE_ID}",
                    conf_payload,
                    timeout=5,
                    method="PUT",
                )
        else:
            # Fallback to JSONL
            log(f"  Core API returned HTTP {http_code}, falling back to JSONL.")
            _write_fallback_jsonl(session_id, topic, storage_content, api_block_type, cwd, tags)
            total_created += 1

    # --- Final sync ---
    if total_created > 0:
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

    # --- Cleanup progressive state ---
    if progressive_file.is_file():
        try:
            progressive_file.unlink()
            log(f"Cleaned up progressive state ({progressive_count} snapshots consumed).")
        except Exception:
            pass

    pipeline_elapsed = time.monotonic() - pipeline_t0
    log(
        f"Done: {total_created} block(s), "
        f"{total_attitudes} attitude(s), "
        f"{total_claude_suggestions} CLAUDE suggestion(s)."
    )
    log(
        f"Stats: transcript={conv_len:,}ch conversation={len(conversation):,}ch "
        f"thinking={thinking_chars:,}ch messages={user_count}u+{assistant_count}a "
        f"progressive={progressive_count} pipeline={pipeline_elapsed:.1f}s"
    )
    sys.exit(0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _call_llm(llm: str, model: str, prompt: str, env: dict) -> "tuple[str | None, float]":
    """Call LLM and return (output_string, elapsed_seconds). Returns (None, elapsed) on failure."""
    t0 = time.monotonic()
    if llm == "gemini":
        cmd = ["gemini", "-m", model, "-p", "按照以下指示分析對話並提煉記憶："]
        result = _run_cmd(cmd, input_text=prompt, env=env, label="Gemini")
    elif llm == "claude":
        cmd = ["claude", "-p", "--model", model]
        result = _run_cmd(cmd, input_text=prompt, env=env, label="Claude")
    elif llm == "codex":
        codex_args = ["codex", "exec", "--skip-git-repo-check"]
        if model:
            codex_args += ["-m", model]
        codex_args.append("-")  # read prompt from stdin
        result = _run_cmd(codex_args, input_text=prompt, env=env, label="Codex")
    else:
        log(f"Unknown LLM: {llm}, skipping.")
        return None, time.monotonic() - t0
    elapsed = time.monotonic() - t0
    return result, elapsed


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


def _http_post(
    url: str, data: bytes, timeout: int = 10, connect_timeout: int = 3, method: str = "POST"
) -> tuple:
    """HTTP request, return (http_code, response_body). Returns (0, '') on error."""
    try:
        headers = {"Content-Type": "application/json"}
        internal_key = os.environ.get("CORE_INTERNAL_API_KEY", "")
        if internal_key:
            headers["X-Internal-Key"] = internal_key
        req = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method=method,
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


def _write_claude_staging(suggestions: list[dict]) -> None:
    """Append CLAUDE.md suggestions to staging JSONL file."""
    staging_dir = Path.home() / ".claude" / "data" / "claudemd-suggestions"
    staging_dir.mkdir(parents=True, exist_ok=True)
    staging_file = staging_dir / "pending.jsonl"
    try:
        with open(staging_file, "a", encoding="utf-8") as f:
            for entry in suggestions:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        log(f"Failed to write CLAUDE.md staging: {e}")


def _write_fallback_jsonl(
    session_id: str,
    topic: str,
    content: str,
    block_type: str,
    project: str,
    tags: list,
) -> None:
    """Write extraction to JSONL file when Core API is unavailable."""
    year_month = datetime.now().strftime("%Y-%m")
    today = datetime.now().strftime("%Y-%m-%d")
    fallback_file = FALLBACK_DIR / year_month / f"{today}.jsonl"
    fallback_file.parent.mkdir(parents=True, exist_ok=True)

    fallback_entry = json.dumps(
        {
            "session_id": session_id,
            "topic": topic,
            "content": content,
            "block_type": block_type,
            "project": project,
            "tags": tags,
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "session_end",
            "ingested": False,
        }
    )

    try:
        with open(fallback_file, "a", encoding="utf-8") as f:
            f.write(fallback_entry + "\n")
        log(f"  Fallback: saved to {fallback_file}")
    except Exception as e:
        log(f"  Failed to write fallback JSONL: {e}")


if __name__ == "__main__":
    main()
