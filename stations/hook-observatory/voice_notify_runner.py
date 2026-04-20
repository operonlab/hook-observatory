#!/usr/bin/env python3
"""
Standalone runner for voice_notify handler.

Invoked by the Go hook-dispatcher to fire ONLY the voice_notify handler —
other Python handlers stay out of the path. Matches the
handle(event_type, tool_name, tool_input, raw_input) signature and fails
silently (fire-and-forget).

Usage:
  python3 voice_notify_runner.py <EVENT_TYPE>  < <raw_json_payload>
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def main() -> None:
    event_type = sys.argv[1] if len(sys.argv) > 1 else ""
    raw = sys.stdin.read()

    data: dict = {}
    try:
        if raw.strip():
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                data = parsed
    except Exception:
        data = {}

    tool_name = str(data.get("tool_name", ""))
    tool_input = data.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}

    try:
        from handlers.voice_notify import handle  # type: ignore

        handle(event_type, tool_name, tool_input, raw)
    except Exception:
        # fire-and-forget: never crash the Go dispatcher
        pass


if __name__ == "__main__":
    main()
