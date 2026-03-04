#!/usr/bin/env python3
"""Memvault V2 — triple extraction pipeline.
Extracts (Subject, Predicate, Object) triples from session transcripts via Gemini.
Writes validated triples to Core API (primary) and JSONL fallback.

Usage:
  stdin JSON {"session_id", "transcript_path", "cwd"}
  OR positional args: <session_id> <transcript_path>
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
LOG_DIR = Path.home() / "Claude" / "memvault" / "logs"
LOG_FILE = LOG_DIR / "extract-triples.log"
TRIPLES_BASE = Path.home() / "Claude" / "memvault" / "triples"
CORRECTIONS_BASE = Path.home() / "Claude" / "memvault" / "corrections"
PROMPT_TEMPLATE = SCRIPT_DIR / "prompts" / "triple-extraction.txt"
VALIDATOR = SCRIPT_DIR / "validate-triples.py"
PYTHON = str(Path.home() / ".local" / "bin" / "python3")

CORE_API = os.environ.get("CORE_API_URL", "http://localhost:8801")
SPACE_ID = os.environ.get("MEMVAULT_SPACE_ID", "default")
KG_BATCH_URL = f"{CORE_API}/api/memvault/kg/triples/batch"

# Prevent recall from firing on internal LLM calls
os.environ["MEMVAULT_SKIP_RECALL"] = "1"

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
    """Write timestamped log message to stderr and log file."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[triples] {ts} {msg}"
    print(line, file=sys.stderr)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 1. Parse input
# ---------------------------------------------------------------------------
def parse_input() -> tuple:
    """Return (session_id, transcript_path) from stdin or args."""
    session_id = ""
    transcript_path = ""

    # If stdin is a TTY and we have args, use positional args
    if sys.stdin.isatty() and len(sys.argv) >= 3:
        session_id = sys.argv[1]
        transcript_path = sys.argv[2]
    else:
        try:
            input_json = json.loads(sys.stdin.read())
        except json.JSONDecodeError:
            return "", ""
        session_id = input_json.get("session_id", "").strip()
        transcript_path = input_json.get("transcript_path", "").strip()

    return session_id, transcript_path


# ---------------------------------------------------------------------------
# 2 & 3. Extract conversation + count exchanges
# ---------------------------------------------------------------------------
def extract_conversation(transcript_path: str) -> str:
    """Parse JSONL transcript, return formatted conversation string."""
    lines = []
    try:
        with open(transcript_path, encoding="utf-8") as f:
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
                    lines.append(f"{role}: {text}")
    except Exception as e:
        log(f"Error reading transcript: {e}")
        return ""

    return "\n".join(lines)


def count_exchanges(conversation: str) -> tuple:
    """Return (user_count, assistant_count)."""
    user_count = sum(1 for line in conversation.splitlines() if line.startswith("USER: "))
    assistant_count = sum(1 for line in conversation.splitlines() if line.startswith("ASSISTANT: "))
    return user_count, assistant_count


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def http_post(url: str, data: bytes, timeout: int = 15) -> tuple:
    """POST request, return (status_code, response_body). Returns (0, '') on error."""
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    session_id, transcript_path = parse_input()

    if not session_id or not transcript_path:
        log("Missing session_id or transcript_path, skipping.")
        sys.exit(0)

    if not Path(transcript_path).is_file():
        log(f"Transcript not found: {transcript_path}")
        sys.exit(0)

    log(f"Processing session {session_id} ...")

    # ---------------------------------------------------------------------------
    # 2 & 3. Extract conversation + count exchanges
    # ---------------------------------------------------------------------------
    conversation = extract_conversation(transcript_path)
    if not conversation:
        log("No conversation content found, skipping.")
        sys.exit(0)

    user_count, assistant_count = count_exchanges(conversation)
    if user_count < 3 or assistant_count < 3:
        pair_count = min(user_count, assistant_count)
        log(f"Only {pair_count} exchange(s), skipping (need >= 3).")
        sys.exit(0)

    # ---------------------------------------------------------------------------
    # 4. Truncate to 30000 chars
    # ---------------------------------------------------------------------------
    conv_len = len(conversation)
    if conv_len > 30000:
        conversation = conversation[-30000:]
        newline_pos = conversation.find("\n")
        if newline_pos != -1:
            conversation = conversation[newline_pos + 1 :]
        log(f"Truncated conversation from {conv_len} to ~30000 chars.")

    # ---------------------------------------------------------------------------
    # 5. Build prompt and call Gemini
    # ---------------------------------------------------------------------------
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    if not PROMPT_TEMPLATE.is_file():
        log(f"Prompt template not found: {PROMPT_TEMPLATE}")
        sys.exit(0)

    try:
        template_text = PROMPT_TEMPLATE.read_text(encoding="utf-8")
    except Exception as e:
        log(f"Failed to read prompt template: {e}")
        sys.exit(0)

    # Substitute template variables (mimics sed substitution)
    prompt_text = template_text.replace("${SESSION_ID}", session_id).replace(
        "${TIMESTAMP}", timestamp
    )
    full_prompt = prompt_text + "\n\n" + conversation

    triple_model = os.environ.get("TRIPLE_MODEL", "gemini-2.5-pro")
    log(f"Calling {triple_model} for triple extraction ...")

    try:
        result = subprocess.run(
            [
                "gemini",
                "-m",
                triple_model,
                "-p",
                "Extract knowledge triples from the conversation below. Output ONLY valid JSON per the instruction.",
            ],
            input=full_prompt,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            log(f"Gemini call failed (exit {result.returncode}), skipping.")
            sys.exit(0)
        raw_output = result.stdout
    except FileNotFoundError:
        log("gemini not found in PATH, skipping.")
        sys.exit(0)
    except subprocess.TimeoutExpired:
        log("Gemini call timed out, skipping.")
        sys.exit(0)
    except Exception as e:
        log(f"Gemini call error: {e}, skipping.")
        sys.exit(0)

    # ---------------------------------------------------------------------------
    # 6. Clean output
    # ---------------------------------------------------------------------------
    clean_lines = []
    for line in raw_output.splitlines():
        if line.startswith("```"):
            continue
        if line.startswith("Created execution plan for "):
            continue
        if line.startswith("Expanding hook command:"):
            continue
        if line.startswith("Hook execution for "):
            continue
        clean_lines.append(line)

    clean_output = "\n".join(clean_lines).strip()

    if not clean_output:
        log("Empty response from Gemini, skipping.")
        sys.exit(0)

    # ---------------------------------------------------------------------------
    # 7. Validate with validate-triples.py
    # ---------------------------------------------------------------------------
    if not VALIDATOR.is_file():
        log(f"Validator not found: {VALIDATOR}")
        sys.exit(0)

    try:
        validate_result = subprocess.run(
            [PYTHON, str(VALIDATOR)],
            input=clean_output,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if validate_result.returncode != 0:
            err_preview = validate_result.stderr[:200] if validate_result.stderr else ""
            raw_preview = clean_output[:100]
            log(f"Validation failed — error: {err_preview}")
            log(f"Validation failed — raw output: {raw_preview}")
            sys.exit(0)
        validated_json_str = validate_result.stdout
    except subprocess.TimeoutExpired:
        log("Validator timed out, skipping.")
        sys.exit(0)
    except Exception as e:
        log(f"Validator error: {e}, skipping.")
        sys.exit(0)

    # ---------------------------------------------------------------------------
    # 8. Check for skip
    # ---------------------------------------------------------------------------
    try:
        validated_json = json.loads(validated_json_str)
    except json.JSONDecodeError as e:
        log(f"Validator output is not valid JSON: {e}, skipping.")
        sys.exit(0)

    if validated_json.get("skip") is True:
        log("Gemini returned skip=true — nothing worth extracting.")
        sys.exit(0)

    # ---------------------------------------------------------------------------
    # 9. Duplicate check (against JSONL fallback store)
    # ---------------------------------------------------------------------------
    year_month = datetime.now().strftime("%Y-%m")
    today = datetime.now().strftime("%Y-%m-%d")
    triples_dir = TRIPLES_BASE / year_month
    triples_file = triples_dir / f"{today}.jsonl"

    triples_dir.mkdir(parents=True, exist_ok=True)

    if triples_file.is_file():
        try:
            content = triples_file.read_text(encoding="utf-8")
            if f'"session_id":"{session_id}"' in content:
                log(f"Session {session_id} already in triples, skipping duplicate.")
                sys.exit(0)
        except Exception:
            pass

    # ---------------------------------------------------------------------------
    # 10. Build batch payload for Core API
    # ---------------------------------------------------------------------------
    topic = validated_json.get("topic", "")
    tags = validated_json.get("tags", [])
    triples = validated_json.get("triples", [])

    batch_triples = []
    for t in triples:
        batch_triples.append(
            {
                "s": t.get("s", ""),
                "p": t.get("p", ""),
                "o": t.get("o", ""),
                "session_id": session_id,
                "topic": topic,
                "tags": tags,
            }
        )

    batch_payload = json.dumps(
        {
            "triples": batch_triples,
            "session_id": session_id,
            "topic": topic,
            "tags": tags,
        }
    ).encode("utf-8")

    # ---------------------------------------------------------------------------
    # 11. POST to Core API (primary path)
    # ---------------------------------------------------------------------------
    core_api_success = False
    if batch_triples:
        http_status, _ = http_post(
            f"{KG_BATCH_URL}?space_id={SPACE_ID}",
            batch_payload,
            timeout=15,
        )
        if http_status in (200, 201):
            log(f"Core API: triples saved (HTTP {http_status})")
            core_api_success = True
        else:
            log(f"Core API unavailable (HTTP {http_status}) — falling back to JSONL")

    # ---------------------------------------------------------------------------
    # 12. JSONL fallback (graceful degradation + archive)
    # ---------------------------------------------------------------------------
    single_line = json.dumps(validated_json, ensure_ascii=False)
    try:
        with open(triples_file, "a", encoding="utf-8") as f:
            f.write(single_line + "\n")
        if core_api_success:
            log(f"Archive: triples mirrored to {triples_file}")
        else:
            log(f"Fallback: triples saved to {triples_file}")
    except Exception as e:
        log(f"Failed to write triples JSONL: {e}")

    # ---------------------------------------------------------------------------
    # 12.5. Triple counter + threshold trigger for auto-synthesis
    # ---------------------------------------------------------------------------
    counter_file = Path.home() / ".memvault-triple-counter"
    triple_count = len(triples)

    current_count = 0
    if counter_file.is_file():
        try:
            raw = counter_file.read_text().strip()
            current_count = int("".join(c for c in raw if c.isdigit()) or "0")
        except Exception:
            current_count = 0

    new_count = current_count + triple_count
    try:
        counter_file.write_text(str(new_count))
    except Exception:
        pass

    log(f"Triple counter: {current_count} + {triple_count} = {new_count}")

    synthesis_threshold = int(os.environ.get("SYNTHESIS_THRESHOLD", "30"))
    if new_count >= synthesis_threshold:
        log(f"Threshold reached ({new_count} >= {synthesis_threshold}) — triggering auto-synthesis")
        pipelines_dir = SCRIPT_DIR.parent / "pipelines"
        cluster_pipeline = pipelines_dir / "cluster_pipeline.py"
        wisdom_pipeline = pipelines_dir / "wisdom_pipeline.py"

        if cluster_pipeline.is_file():
            synthesis_log = LOG_DIR / "synthesis.log"
            proc = subprocess.Popen(
                [PYTHON, str(cluster_pipeline)],
                stdout=open(synthesis_log, "a"),
                stderr=subprocess.STDOUT,
            )
            log(f"Auto-synthesis launched in background (PID {proc.pid})")

            if wisdom_pipeline.is_file():
                subprocess.Popen(
                    [PYTHON, str(wisdom_pipeline)],
                    stdout=open(synthesis_log, "a"),
                    stderr=subprocess.STDOUT,
                )

        try:
            counter_file.write_text("0")
        except Exception:
            pass

    # ---------------------------------------------------------------------------
    # 13. Extract corrections to corrections JSONL
    # ---------------------------------------------------------------------------
    corrections = validated_json.get("corrections", [])
    correction_count = len(corrections)

    if correction_count > 0:
        corrections_dir = CORRECTIONS_BASE / year_month
        corrections_file = corrections_dir / f"{today}.jsonl"
        corrections_dir.mkdir(parents=True, exist_ok=True)

        try:
            with open(corrections_file, "a", encoding="utf-8") as f:
                for correction in corrections:
                    record = dict(correction)
                    record["session_id"] = session_id
                    record["timestamp"] = timestamp
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            log(f"{correction_count} correction(s) saved to {corrections_file}")
        except Exception as e:
            log(f"Failed to write corrections: {e}")

    log("Done.")
    sys.exit(0)


if __name__ == "__main__":
    main()
