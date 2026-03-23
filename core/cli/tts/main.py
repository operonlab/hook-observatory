#!/Users/joneshong/.local/bin/python3
"""TTS CLI — Text-to-speech synthesis.

Usage:
    tts synthesize <text> [--voice VOICE] [--speed SPEED] [--engine ENGINE]
    tts voices [--engine ENGINE]
    tts engines
    tts health

Symlink: ln -sf ~/workshop/core/cli/tts/main.py ~/.local/bin/tts
"""

import argparse
import json
import sys

from workshop.clients._base import APIError
from workshop.clients.tts import TTSClient


def cmd_synthesize(args):
    client = TTSClient()
    try:
        result = client.synthesize(
            text=args.text,
            voice=args.voice,
            speed=args.speed,
            engine=args.engine,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except APIError as e:
        print(f"Error ({e.status_code}): {e.detail}", file=sys.stderr)
        sys.exit(1)


def cmd_voices(args):
    client = TTSClient()
    try:
        result = client.list_voices(engine=args.engine)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except APIError as e:
        print(f"Error ({e.status_code}): {e.detail}", file=sys.stderr)
        sys.exit(1)


def cmd_engines(args):
    client = TTSClient()
    try:
        result = client.list_engines()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except APIError as e:
        print(f"Error ({e.status_code}): {e.detail}", file=sys.stderr)
        sys.exit(1)


def cmd_health(args):
    client = TTSClient()
    try:
        result = client.health()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except APIError:
        print("Error: TTS station not reachable", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="TTS CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # synthesize
    p_syn = sub.add_parser("synthesize", help="Synthesize speech from text")
    p_syn.add_argument("text", help="Text to synthesize")
    p_syn.add_argument("--voice", default="default", help="Voice ID (default: default)")
    p_syn.add_argument("--speed", type=float, default=1.0, help="Speed multiplier (default: 1.0)")
    p_syn.add_argument("--engine", default="apple", help="Engine name (default: apple)")
    p_syn.set_defaults(func=cmd_synthesize)

    # voices
    p_voices = sub.add_parser("voices", help="List available voices")
    p_voices.add_argument("--engine", default="apple", help="Engine name (default: apple)")
    p_voices.set_defaults(func=cmd_voices)

    # engines
    p_eng = sub.add_parser("engines", help="List available engines")
    p_eng.set_defaults(func=cmd_engines)

    # health
    p_health = sub.add_parser("health", help="Check TTS station health")
    p_health.set_defaults(func=cmd_health)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
