#!/usr/bin/env python3
"""workshop-tts CLI — thin wrapper over sdk_client.tts.TTSClient v2 API.

Usage:
  workshop-tts --text "你好" --lang zh                          # → /tmp/tts_xxx.wav
  workshop-tts --text "Hello" --lang en --out /tmp/o.wav         # FILE mode
  workshop-tts --text "..." --lang zh --output base64            # base64 JSON
  workshop-tts --text "..." --lang zh --output buffer > out.wav  # wav bytes to stdout
  workshop-tts --text "..." --lang ja --engine indextts2_jmica   # force engine

  workshop-tts list-engines
  workshop-tts list-voices
  workshop-tts route --lang en --prefer-fast
  workshop-tts healthcheck
  workshop-tts lifecycle status | sweep
"""

from __future__ import annotations

import argparse
import base64
import json
import sys

from sdk_client.tts import TTSClient


def cmd_synthesize(args, client: TTSClient) -> int:
    engine_specific = {}
    if args.ref_text:
        engine_specific["ref_text"] = args.ref_text
    if args.instruct:
        engine_specific["instruct"] = args.instruct

    res = client.synthesize_v2(
        text=args.text,
        lang=args.lang,
        voice=args.voice,
        engine=args.engine,
        output=args.output,
        out_path=args.out,
        target_sample_rate=args.sample_rate,
        speed=args.speed,
        engine_specific=engine_specific or None,
    )

    if args.output == "buffer":
        b64 = res.get("audio_bytes_b64", "")
        if not b64:
            print("Server returned no audio_bytes_b64", file=sys.stderr)
            return 1
        sys.stdout.buffer.write(base64.b64decode(b64))
        return 0

    if args.output == "base64":
        # JSON stdout for piping
        print(json.dumps(res, ensure_ascii=False))
        return 0

    # file / numpy / tensor / stream → 打印摘要
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        path = res.get("audio_path", "?")
        rtf = res.get("rtf", "?")
        dur = res.get("duration_s", "?")
        eng = res.get("engine", "?")
        print(f"[{eng}] {dur}s @ RTF={rtf}  →  {path}")
    return 0


def cmd_list_engines(args, client: TTSClient) -> int:
    data = client.list_engines_v2()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    print(f"v{data.get('version', '?')} — {data.get('count', 0)} engines\n")
    for e in data.get("engines", []):
        ok = "✓" if e.get("healthy") else "✗"
        langs = ",".join(e.get("languages", []))
        wsl = " WSL2" if e.get("needs_wsl") else ""
        print(
            f"  {ok} {e['name']:30} lang=[{langs:14}] RTF={e['rtf_typical']:.2f} "
            f"VRAM={e['vram_mb']}MB{wsl}"
        )
        if e.get("notes"):
            print(f"      └─ {e['notes'].splitlines()[0]}")
    return 0


def cmd_list_voices(args, client: TTSClient) -> int:
    data = client.list_voices_v2()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    print(f"voices_dir={data.get('voices_dir')}")
    for v in data.get("voices", []):
        t = "✓" if v["has_transcript"] else "✗"
        m = "✓" if v["has_meta"] else "✗"
        print(f"  • {v['voice_id']:20} transcript={t}  meta={m}")
    return 0


def cmd_route(args, client: TTSClient) -> int:
    res = client.explain_route(args.lang, multi_speaker=args.multi_speaker, prefer_fast=args.prefer_fast)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(f"primary: {res['primary']}")
        print(f"chain:   {' → '.join(res.get('fallback_chain', []))}")
    return 0


def cmd_healthcheck(args, client: TTSClient) -> int:
    res = client.healthz_v2()
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    for name, h in res.get("engines", {}).items():
        ok = "✓" if h.get("ok") else "✗"
        print(f"  {ok} {name:30}  {h}")
    return 0 if all(h.get("ok") for h in res.get("engines", {}).values()) else 1


def cmd_lifecycle(args, client: TTSClient) -> int:
    if args.action == "status":
        res = client.lifecycle_status()
    elif args.action == "sweep":
        res = client.lifecycle_sweep()
    else:
        print(f"unknown action: {args.action}", file=sys.stderr)
        return 2
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="workshop-tts", description="Workshop TTS station CLI (v2 API)")
    p.add_argument("--base-url", help="Override base URL (default uses port_registry)")
    p.add_argument("--json", action="store_true", help="Output JSON")
    sub = p.add_subparsers(dest="command")

    # Default subcommand: synthesize
    syn = sub.add_parser("synthesize", help="Synthesize speech (default)")
    syn.add_argument("--text", required=True)
    syn.add_argument("--lang", required=True, choices=["zh", "en", "ja", "ko", "auto"])
    syn.add_argument("--voice", default="master")
    syn.add_argument("--engine", default="auto")
    syn.add_argument("--output", default="file",
                     choices=["file", "buffer", "numpy", "tensor", "base64", "stream"])
    syn.add_argument("--out", help="output path (FILE mode)")
    syn.add_argument("--sample-rate", type=int)
    syn.add_argument("--speed", type=float, default=1.0)
    syn.add_argument("--ref-text", help="reference transcript (qwen3tts zero-shot 必填)")
    syn.add_argument("--instruct", help="instruct prompt (cosyvoice)")

    le = sub.add_parser("list-engines")  # noqa: F841
    lv = sub.add_parser("list-voices")  # noqa: F841

    rt = sub.add_parser("route", help="Explain auto-routing for given lang")
    rt.add_argument("--lang", required=True)
    rt.add_argument("--multi-speaker", action="store_true")
    rt.add_argument("--prefer-fast", action="store_true")

    sub.add_parser("healthcheck")  # noqa

    lc = sub.add_parser("lifecycle")
    lc.add_argument("action", choices=["status", "sweep"])

    # Aliases for ergonomic CLI (workshop-tts --text "..." without subcmd)
    p.add_argument("--text", help=argparse.SUPPRESS)
    p.add_argument("--lang", help=argparse.SUPPRESS)
    p.add_argument("--voice", default="master", help=argparse.SUPPRESS)
    p.add_argument("--engine", default="auto", help=argparse.SUPPRESS)
    p.add_argument("--output", default="file", help=argparse.SUPPRESS)
    p.add_argument("--out", help=argparse.SUPPRESS)
    p.add_argument("--sample-rate", type=int, help=argparse.SUPPRESS)
    p.add_argument("--speed", type=float, default=1.0, help=argparse.SUPPRESS)
    p.add_argument("--ref-text", help=argparse.SUPPRESS)
    p.add_argument("--instruct", help=argparse.SUPPRESS)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Bare-form ergonomic alias: `workshop-tts --text X --lang zh` → synthesize
    if args.command is None and args.text and args.lang:
        args.command = "synthesize"

    client = TTSClient(base_url=args.base_url)
    try:
        if args.command == "synthesize":
            return cmd_synthesize(args, client)
        elif args.command == "list-engines":
            return cmd_list_engines(args, client)
        elif args.command == "list-voices":
            return cmd_list_voices(args, client)
        elif args.command == "route":
            return cmd_route(args, client)
        elif args.command == "healthcheck":
            return cmd_healthcheck(args, client)
        elif args.command == "lifecycle":
            return cmd_lifecycle(args, client)
        else:
            parser.print_help()
            return 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
