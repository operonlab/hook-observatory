"""SessionEnd: unified pipeline handler.

Replaces the individual external.redact_session + external.extract +
observability.handle calls with a single, ordered pipeline:
  1. redact  — clean sensitive data
  2. extract — memvault knowledge extraction
  3. archive — session-archiver scan
  4. log     — observatory event logging

The pipeline runs as a background process so the hook returns immediately
without blocking Claude Code.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys

from .base import ALLOW, HookResult

log = logging.getLogger(__name__)


def handle(
    event_type: str,
    tool_name: str,
    tool_input: dict,
    raw_input: str,
) -> HookResult:
    """Run the session pipeline on SessionEnd (non-blocking)."""
    try:
        data = json.loads(raw_input) if raw_input else {}
        session_id = data.get("session_id", "")
        transcript_path = data.get("transcript_path")

        if not session_id:
            return ALLOW

        # Spawn the pipeline as a fully detached background process.
        # Using a Python one-liner avoids needing a separate script file and
        # keeps the hook return time near-zero.
        code = (
            "import sys, os; "
            "sys.path.insert(0, os.path.expanduser('~/workshop/libs/python/src')); "
            "from workshop.clients.session_pipeline import SessionPipelineClient; "
            f"SessionPipelineClient().run_pipeline({session_id!r}, {transcript_path!r})"
        )
        subprocess.Popen(
            [sys.executable, "-c", code],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        pass  # fail-open: never block Claude Code

    return ALLOW
