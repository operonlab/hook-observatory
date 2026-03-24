#!/usr/bin/env python3
"""TPS CLI — Translation Proxy Station command-line interface.

Usage:
    tps translate "Hello world" --to zh-TW
    tps batch input.txt --to zh-TW --output output.txt
    tps usage
    tps providers
"""

from __future__ import annotations

import argparse
import json
import sys


def _get_client():
    from workshop.clients.tps import TPSClient

    return TPSClient()


def cmd_translate(args: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="tps translate")
    parser.add_argument("text", help="Text to translate")
    parser.add_argument("--from", dest="source_lang", default="auto")
    parser.add_argument("--to", dest="target_lang", default="zh-TW")
    parser.add_argument("--provider", default=None, help="Force provider (deepl/google)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    opts = parser.parse_args(args)

    client = _get_client()
    result = client.translate(
        opts.text,
        source_lang=opts.source_lang,
        target_lang=opts.target_lang,
        provider=opts.provider,
    )

    if opts.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        cached = " (cached)" if result.get("cached") else ""
        provider = result.get("provider", "?")
        print(f"[{provider}{cached}] {result['text']}")


def cmd_batch(args: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="tps batch")
    parser.add_argument("file", help="Input file (one text per line)")
    parser.add_argument("--from", dest="source_lang", default="auto")
    parser.add_argument("--to", dest="target_lang", default="zh-TW")
    parser.add_argument("--output", "-o", default=None, help="Output file")
    opts = parser.parse_args(args)

    with open(opts.file) as f:
        texts = [line.strip() for line in f if line.strip()]

    if not texts:
        print("No texts found in file.", file=sys.stderr)
        return

    client = _get_client()
    result = client.batch_translate(texts, opts.source_lang, opts.target_lang)

    lines = [r["text"] for r in result.get("results", [])]
    output = "\n".join(lines)

    if opts.output:
        with open(opts.output, "w") as f:
            f.write(output + "\n")
        print(f"Translated {len(lines)} lines → {opts.output}")
    else:
        print(output)


def cmd_usage(args: list[str]) -> None:
    client = _get_client()
    data = client.usage()
    print(f"Date: {data.get('date', '?')}")
    print(f"Budget: ${data.get('budget_remaining_usd', 0):.2f} / ${data.get('daily_budget_usd', 0):.2f}")
    for name, stats in data.get("providers", {}).items():
        chars = stats.get("char_count", 0)
        reqs = stats.get("request_count", 0)
        cost = stats.get("estimated_cost_usd", 0)
        print(f"  {name}: {chars:,} chars, {reqs} requests, ${cost:.4f}")


def cmd_providers(args: list[str]) -> None:
    client = _get_client()
    health = client.health()
    for name, available in health.get("providers", {}).items():
        status = "OK" if available else "UNAVAILABLE"
        print(f"  {name}: {status}")


def main():
    parser = argparse.ArgumentParser(prog="tps", description="Translation Proxy Station CLI")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("translate", help="Translate text")
    subparsers.add_parser("batch", help="Batch translate from file")
    subparsers.add_parser("usage", help="Show usage stats")
    subparsers.add_parser("providers", help="List providers")

    # Parse only the command name
    args, remaining = parser.parse_known_args()

    commands = {
        "translate": cmd_translate,
        "batch": cmd_batch,
        "usage": cmd_usage,
        "providers": cmd_providers,
    }

    if args.command in commands:
        commands[args.command](remaining)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
