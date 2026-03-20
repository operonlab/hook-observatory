#!/Users/joneshong/.local/bin/python3
"""STT CLI — Speech-to-text transcription.

Usage:
    stt transcribe <audio-file> [--language LANG] [--engine ENGINE]
    stt engines
    stt health

Symlink: ln -sf ~/workshop/core/cli/stt/main.py ~/.local/bin/stt
"""

import argparse
import json
import sys

from workshop.clients.stt import STTClient
from workshop.clients._base import APIError


def cmd_transcribe(args):
    client = STTClient()
    try:
        result = client.transcribe(
            file_path=args.file,
            language=args.language,
            engine=args.engine,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except APIError as e:
        print(f"Error ({e.status_code}): {e.detail}", file=sys.stderr)
        sys.exit(1)


def cmd_engines(args):
    client = STTClient()
    try:
        result = client.list_engines()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except APIError as e:
        print(f"Error ({e.status_code}): {e.detail}", file=sys.stderr)
        sys.exit(1)


def cmd_health(args):
    client = STTClient()
    try:
        result = client.health()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except APIError as e:
        print(f"Error: STT station not reachable", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="STT CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # transcribe
    p_trans = sub.add_parser("transcribe", help="Transcribe audio file")
    p_trans.add_argument("file", help="Path to audio file")
    p_trans.add_argument("--language", default="zh-TW", help="Language code (default: zh-TW)")
    p_trans.add_argument("--engine", default="apple", help="Engine name (default: apple)")
    p_trans.set_defaults(func=cmd_transcribe)

    # engines
    p_eng = sub.add_parser("engines", help="List available engines")
    p_eng.set_defaults(func=cmd_engines)

    # health
    p_health = sub.add_parser("health", help="Check STT station health")
    p_health.set_defaults(func=cmd_health)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
