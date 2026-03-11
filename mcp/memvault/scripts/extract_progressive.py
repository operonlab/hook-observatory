#!/usr/bin/env python3
"""Progressive extraction — mid-session memory capture via PreCompact hook.

Triggered by PreCompact hook (both manual /compact and auto-compact).
Reads the transcript up to this point, compares with prior progressive state,
extracts only NEW insights, and stores them as progressive snapshots.

At SessionEnd, extract.py can optionally read the progressive state file
to provide richer context (prior observations from earlier compactions).

Design: Mi = LLM(Si, Mi-1, Pm) where:
  Si = current transcript segment (since last progressive extraction)
  Mi-1 = prior progressive state
  Pm = progressive extraction prompt

stdin: JSON {"session_id", "transcript_path", "cwd", "trigger", ...}

State files:
  ~/Claude/memvault/progressive/{session_id}.json — cumulative progressive state
"""

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LOG_DIR = Path.home() / "Claude" / "memvault" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "progressive.log"

PROGRESSIVE_DIR = Path.home() / "Claude" / "memvault" / "progressive"
PROGRESSIVE_DIR.mkdir(parents=True, exist_ok=True)

PYTHON = str(Path.home() / ".local" / "bin" / "python3")


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[progressive] {ts} {msg}"
    print(line, file=sys.stderr)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def main() -> None:
    try:
        input_json = json.loads(sys.stdin.read())
    except json.JSONDecodeError as e:
        log(f"Invalid JSON input: {e}")
        sys.exit(0)

    session_id = input_json.get("session_id", "").strip()
    transcript_path = input_json.get("transcript_path", "").strip()
    trigger = input_json.get("trigger", "unknown")

    if not session_id or not transcript_path:
        log("Missing session_id or transcript_path, skipping.")
        sys.exit(0)

    transcript = Path(transcript_path)
    if not transcript.is_file():
        log(f"Transcript not found: {transcript_path}")
        sys.exit(0)

    log(f"PreCompact trigger={trigger} session={session_id}")

    # ---------------------------------------------------------------------------
    # 1. Read transcript — lightweight version (text only, no tool results)
    # ---------------------------------------------------------------------------
    conversation_lines = []
    line_count = 0
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
                line_count += 1

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
                            text = item.get("text", "")
                            if text.strip() and len(text) > 100:
                                parts.append(f"[THINKING] {text[:1000]}")
                    if parts:
                        role = "USER" if entry_type == "user" else "ASSISTANT"
                        conversation_lines.append(f"{role}: " + "\n".join(parts))
    except Exception as e:
        log(f"Error reading transcript: {e}")
        sys.exit(0)

    if line_count < 4:
        log(f"Only {line_count} messages, too short for progressive extraction.")
        sys.exit(0)

    # ---------------------------------------------------------------------------
    # 2. Load prior progressive state (if any)
    # ---------------------------------------------------------------------------
    state_file = PROGRESSIVE_DIR / f"{session_id}.json"
    prior_state = None
    prior_line_count = 0

    if state_file.is_file():
        try:
            prior_state = json.loads(state_file.read_text(encoding="utf-8"))
            prior_line_count = prior_state.get("line_count", 0)
        except Exception:
            prior_state = None

    # Skip if no significant new content since last extraction
    new_lines = line_count - prior_line_count
    if new_lines < 4:
        log(f"Only {new_lines} new messages since last progressive, skipping.")
        sys.exit(0)

    # ---------------------------------------------------------------------------
    # 3. Build progressive prompt
    # ---------------------------------------------------------------------------
    conversation = "\n".join(conversation_lines)
    # Truncate to 30K chars (progressive uses lighter LLM)
    if len(conversation) > 30_000:
        conversation = conversation[-30_000:]
        nl = conversation.find("\n")
        if nl != -1:
            conversation = conversation[nl + 1 :]

    prior_observations = ""
    if prior_state and prior_state.get("observations"):
        prior_observations = "\n".join(f"- {obs}" for obs in prior_state["observations"])

    prompt = f"""你是對話記憶的中途快照員。這是一個進行中的 Claude Code session，即將壓縮對話。
在壓縮前，快速記錄到目前為止值得記住的觀察點。

## 任務
從對話中提煉 3-8 個簡短觀察（每條 1-2 句話）。聚焦：
1. 使用者做了什麼技術決策？為什麼？
2. 遇到了什麼問題？如何解決？
3. 使用者表達了什麼偏好？

## 規則
- 每條觀察精簡有力（不超過 80 字）
- 保留具體的：檔案路徑、函數名、版本號、指令
- 不要重複已有的觀察
- 如果沒有值得記住的內容，回傳 {{"skip": true}}

{f"## 先前已記錄的觀察（不要重複這些）{chr(10)}{prior_observations}" if prior_observations else ""}

## 輸出格式（JSON，不加 code fence）
{{
  "observations": [
    "觀察 1：具體的技術發現或決策",
    "觀察 2：遇到的問題和解法"
  ]
}}

---

對話（到目前為止）：

{conversation}"""

    # ---------------------------------------------------------------------------
    # 4. Call LLM (lightweight — use Claude Haiku for speed)
    # ---------------------------------------------------------------------------
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env["MEMVAULT_SKIP_RECALL"] = "1"

    progressive_model = os.environ.get("MEMVAULT_PROGRESSIVE_MODEL", "haiku")
    log(f"Calling Claude ({progressive_model}) for progressive extraction ...")

    t0 = time.monotonic()
    try:
        result = subprocess.run(
            ["claude", "-p", "--model", progressive_model],
            input=prompt,
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        elapsed = time.monotonic() - t0

        if result.returncode != 0:
            log(f"Claude call failed (exit {result.returncode}) in {elapsed:.1f}s.")
            sys.exit(0)

        output = result.stdout.strip()
        log(f"Claude returned in {elapsed:.1f}s ({len(output)} chars).")
    except FileNotFoundError:
        log("Claude not found in PATH.")
        sys.exit(0)
    except subprocess.TimeoutExpired:
        log("Claude call timed out (60s).")
        sys.exit(0)
    except Exception as e:
        log(f"Claude call error: {e}")
        sys.exit(0)

    # ---------------------------------------------------------------------------
    # 5. Parse response and update progressive state
    # ---------------------------------------------------------------------------
    if not output:
        log("Empty response, skipping.")
        sys.exit(0)

    # Strip code fences
    if output.startswith("```"):
        lines = output.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        output = "\n".join(lines)

    json_start = output.find("{")
    json_end = output.rfind("}") + 1
    if json_start == -1 or json_end <= json_start:
        log("No JSON found in response.")
        sys.exit(0)

    try:
        data = json.loads(output[json_start:json_end])
    except json.JSONDecodeError as e:
        log(f"JSON parse failed: {e}")
        sys.exit(0)

    if data.get("skip", False):
        log("LLM says skip — nothing worth noting.")
        sys.exit(0)

    new_observations = data.get("observations", [])
    if not new_observations:
        log("No observations returned.")
        sys.exit(0)

    # Merge with prior observations
    all_observations = []
    if prior_state and prior_state.get("observations"):
        all_observations.extend(prior_state["observations"])
    all_observations.extend(new_observations)

    # Cap at 20 observations (drop oldest if exceeded)
    if len(all_observations) > 20:
        all_observations = all_observations[-20:]

    # Save updated state
    state = {
        "session_id": session_id,
        "line_count": line_count,
        "observations": all_observations,
        "updated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "compaction_count": (prior_state.get("compaction_count", 0) if prior_state else 0) + 1,
    }

    try:
        state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        log(
            f"Saved {len(new_observations)} new + {len(all_observations) - len(new_observations)} prior "
            f"= {len(all_observations)} total observations."
        )
    except Exception as e:
        log(f"Failed to save state: {e}")

    sys.exit(0)


if __name__ == "__main__":
    main()
