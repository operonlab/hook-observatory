#!/Users/joneshong/.local/bin/python3
"""OCR CLI — Text extraction from images and PDFs.

Usage:
    ocr extract <file> [--languages LANGS] [--engine ENGINE]
    ocr engines
    ocr health

Symlink: ln -sf ~/workshop/core/cli/ocr/main.py ~/.local/bin/ocr
"""

import argparse
import json
import sys

from workshop.clients.ocr import OCRClient
from workshop.clients._base import APIError


def cmd_extract(args):
    client = OCRClient()
    try:
        languages = args.languages.split(",") if args.languages else None
        result = client.extract(
            file_path=args.file,
            languages=languages,
            engine=args.engine,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except APIError as e:
        print(f"Error ({e.status_code}): {e.detail}", file=sys.stderr)
        sys.exit(1)


def cmd_engines(args):
    client = OCRClient()
    try:
        result = client.list_engines()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except APIError as e:
        print(f"Error ({e.status_code}): {e.detail}", file=sys.stderr)
        sys.exit(1)


def cmd_health(args):
    client = OCRClient()
    try:
        result = client.health()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except APIError as e:
        print(f"Error: OCR station not reachable", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="OCR CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # extract
    p_ext = sub.add_parser("extract", help="Extract text from image or PDF")
    p_ext.add_argument("file", help="Path to image or PDF file")
    p_ext.add_argument("--languages", default=None, help="Comma-separated language codes (default: zh-Hant,en)")
    p_ext.add_argument("--engine", default="apple", help="Engine name (default: apple)")
    p_ext.set_defaults(func=cmd_extract)

    # engines
    p_eng = sub.add_parser("engines", help="List available engines")
    p_eng.set_defaults(func=cmd_engines)

    # health
    p_health = sub.add_parser("health", help="Check OCR station health")
    p_health.set_defaults(func=cmd_health)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
