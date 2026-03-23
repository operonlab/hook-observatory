#!/Users/joneshong/.local/bin/python3
"""Vision CLI — Visual analysis.

Usage:
    vision analyze <image> [--task TASK] [--engine ENGINE] [--prompt PROMPT]
    vision engines
    vision health

Symlink: ln -sf ~/workshop/core/cli/vision/main.py ~/.local/bin/vision
"""

import argparse
import json
import sys

from workshop.clients._base import APIError
from workshop.clients.vision import VisionClient


def cmd_analyze(args):
    client = VisionClient()
    try:
        result = client.analyze(
            file_path=args.file,
            task=args.task,
            engine=args.engine,
            prompt=args.prompt,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except APIError as e:
        print(f"Error ({e.status_code}): {e.detail}", file=sys.stderr)
        sys.exit(1)


def cmd_engines(args):
    client = VisionClient()
    try:
        result = client.list_engines()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except APIError as e:
        print(f"Error ({e.status_code}): {e.detail}", file=sys.stderr)
        sys.exit(1)


def cmd_health(args):
    client = VisionClient()
    try:
        result = client.health()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except APIError:
        print("Error: Vision station not reachable", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Vision CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # analyze
    p_analyze = sub.add_parser("analyze", help="Analyze image")
    p_analyze.add_argument("file", help="Path to image file")
    p_analyze.add_argument(
        "--task",
        default="describe",
        choices=["describe", "detect", "classify", "qa", "barcode", "face"],
        help="Analysis task (default: describe)",
    )
    p_analyze.add_argument("--engine", default="apple", help="Engine name (default: apple)")
    p_analyze.add_argument("--prompt", default=None, help="Question for task=qa")
    p_analyze.set_defaults(func=cmd_analyze)

    # engines
    p_eng = sub.add_parser("engines", help="List available engines")
    p_eng.set_defaults(func=cmd_engines)

    # health
    p_health = sub.add_parser("health", help="Check Vision station health")
    p_health.set_defaults(func=cmd_health)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
