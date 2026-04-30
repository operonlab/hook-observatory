#!/usr/bin/env python3
"""extract_async.py — Async wrapper for memvault extraction.
Triggered by Claude Code SessionEnd hook.
Captures hook input, backgrounds extract.py + extract_triples.py, exits immediately.

Pipeline:
  1. extract.py         — Memory block extraction (LLM + refinement → Core API)
  2. extract_triples.py — KG triple extraction (Gemini → Core API /kg/triples/batch)

Usage in ~/.claude/settings.json:
  "hooks": { "SessionEnd": [{ "type": "command",
    "command": "~/workshop/mcp/memvault/scripts/extract_async.py",
    "timeout": 5 }] }
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
EXTRACT_SCRIPT = SCRIPT_DIR / "extract.py"
TRIPLES_SCRIPT = SCRIPT_DIR / "extract_triples.py"
LOG_DIR = Path.home() / "Claude" / "memvault" / "logs"
PYTHON = str(Path.home() / ".local" / "bin" / "python3")

LOG_DIR.mkdir(parents=True, exist_ok=True)


def main() -> None:
    # Read hook input from stdin
    input_json = sys.stdin.read()

    # Save to temp file for the background processes
    with tempfile.NamedTemporaryFile(
        mode="w",
        prefix="memvault-extract-",
        suffix=".json",
        dir="/tmp",
        delete=False,
    ) as tmpf:
        tmpf.write(input_json)
        tmpfile_path = tmpf.name

    # Unset CLAUDECODE to allow claude -p calls in background
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)

    # Launch both pipelines + cleanup in a background process
    # We use a wrapper script via subprocess.Popen so the parent can exit immediately
    wrapper_code = f"""
import subprocess
import sys
import os
from pathlib import Path

tmpfile = {tmpfile_path!r}
log_dir = Path({str(LOG_DIR)!r})
extract_script = {str(EXTRACT_SCRIPT)!r}
triples_script = {str(TRIPLES_SCRIPT)!r}
python = {PYTHON!r}
pipelines_dir = {str(SCRIPT_DIR.parent / "pipelines")!r}

extract_log = str(log_dir / "extract-v2.log")
triples_log = str(log_dir / "extract-triples.log")
attitude_log = str(log_dir / "attitude-digest.log")

# Read input data
with open(tmpfile, "rb") as f:
    data = f.read()

# Check transcript exists, fallback to project dir search
try:
    import json as _json
    _hook_input = _json.loads(data.decode("utf-8"))
    _transcript_path = (_hook_input.get("transcript_path") or "").strip()
    _session_id = (_hook_input.get("session_id") or "").strip()
    if _transcript_path and not Path(_transcript_path).exists() and _session_id:
        # Search in ~/.claude/projects/ for matching session JSONL
        _projects = Path.home() / ".claude" / "projects"
        _found = None
        if _projects.exists():
            for _candidate in _projects.rglob(_session_id + ".jsonl"):
                _found = str(_candidate)
                break
        if _found:
            _hook_input["transcript_path"] = _found
            data = _json.dumps(_hook_input).encode("utf-8")
except Exception:
    pass

# Launch memory block extraction
block_proc = None
if Path(extract_script).is_file():
    with open(extract_log, "ab") as lf:
        block_proc = subprocess.Popen(
            [python, extract_script],
            stdin=subprocess.PIPE,
            stdout=lf,
            stderr=lf,
        )
        block_proc.stdin.write(data)
        block_proc.stdin.close()

# Launch KG triple extraction (in parallel)
triple_proc = None
if Path(triples_script).is_file():
    with open(triples_log, "ab") as lf:
        triple_proc = subprocess.Popen(
            [python, triples_script],
            stdin=subprocess.PIPE,
            stdout=lf,
            stderr=lf,
        )
        triple_proc.stdin.write(data)
        triple_proc.stdin.close()

# Wait for both to complete
exit_codes = []
if triple_proc:
    triple_proc.wait()
    exit_codes.append(triple_proc.returncode)
if block_proc:
    block_proc.wait()
    exit_codes.append(block_proc.returncode)

# Digest today's corrections into attitude pipeline (non-blocking, best-effort)
from datetime import datetime
today = datetime.now().strftime("%Y-%m-%d")
year_month = datetime.now().strftime("%Y-%m")
corrections_dir = Path.home() / "Claude" / "memvault" / "corrections"
today_corrections = corrections_dir / year_month / (today + ".jsonl")
attitude_pipeline = Path(pipelines_dir) / "attitude_pipeline.py"

if today_corrections.is_file() and attitude_pipeline.is_file():
    try:
        with open(attitude_log, "ab") as lf:
            subprocess.run(
                [python, str(attitude_pipeline), "--input", str(today_corrections)],
                stdout=lf,
                stderr=lf,
                timeout=120,
            )
    except Exception:
        pass

# Cleanup temp file
try:
    import os as _os
    _os.unlink(tmpfile)
except Exception:
    pass
"""

    # Launch wrapper as completely detached background process
    proc = subprocess.Popen(
        [PYTHON, "-c", wrapper_code],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # replaces disown
    )

    # Return immediately — SessionEnd hooks must not block
    sys.exit(0)


if __name__ == "__main__":
    main()
