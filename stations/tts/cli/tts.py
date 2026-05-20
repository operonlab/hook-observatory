#!/usr/bin/env python3
"""workshop-tts CLI — thin wrapper over sdk_client.tts.TTSClient v2 API.

Usage:
  workshop-tts --text "你好" --lang zh                          # → /tmp/tts_xxx.wav
  workshop-tts --text "Hello" --lang en --out /tmp/o.wav         # FILE mode
  workshop-tts --text "..." --lang zh --output base64            # base64 JSON
  workshop-tts --text "..." --lang zh --output buffer > out.wav  # wav bytes to stdout
  workshop-tts --text "..." --lang ja --engine indextts2_jmica   # force engine

  workshop-tts long --text "...(long paragraph)" --lang zh --out long.wav
  workshop-tts stream --text "..." --lang zh --out stream.wav  # SSE pseudo-streaming
  workshop-tts stream --text "..." --lang zh --engine vibevoice --segments-dir /tmp/segs

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


def cmd_long(args, client: TTSClient) -> int:
    """Long-text synthesis: text segmented + concatenated server-side.

    Output always travels as base64 (server-side FILE mode would write to a
    server-local path, which is the wrong filesystem when station runs on
    win-gpu and CLI runs on Mac). CLI decodes and writes locally.
    """
    res = client.synthesize_long(
        text=args.text,
        lang=args.lang,
        voice=args.voice,
        engine=args.engine,
        output="base64",
        max_chars=args.max_chars,
        speed=args.speed,
    )

    audio_b64 = res.get("audio_base64") or res.get("audio_bytes_b64", "")
    if not audio_b64:
        print(
            f"Server returned no audio. Response: {json.dumps(res, ensure_ascii=False)[:200]}",
            file=sys.stderr,
        )
        return 1
    audio_bytes = base64.b64decode(audio_b64)

    if args.output == "buffer":
        sys.stdout.buffer.write(audio_bytes)
        return 0
    if args.output == "base64":
        print(json.dumps(res, ensure_ascii=False))
        return 0

    # file mode: write locally
    if not args.out:
        import tempfile

        args.out = tempfile.mktemp(suffix=".wav", prefix=f"tts_long_{res.get('engine', 'x')}_")
    with open(args.out, "wb") as f:
        f.write(audio_bytes)

    if args.json:
        print(json.dumps({**res, "audio_path": args.out}, ensure_ascii=False, indent=2))
    else:
        eng = res.get("engine", "?")
        dur = res.get("duration_s", "?")
        segs = res.get("segments", "?")
        seg_durs = res.get("seg_durations_s", [])
        print(f"[{eng}] long: {dur}s in {segs} seg(s)  →  {args.out}")
        if args.verbose and seg_durs:
            for i, d in enumerate(seg_durs):
                print(f"  seg[{i}] {d}s")
    return 0


def cmd_stream(args, client: TTSClient) -> int:
    """SSE pseudo-streaming: per-segment audio events; rebuilds full wav locally."""
    import time as _time
    from pathlib import Path

    import numpy as np
    import soundfile as sf

    t0 = _time.monotonic()
    pre_roll = 0.0
    sr = 24000
    audio_chunks: list[np.ndarray] = []
    seg_dir = Path(args.segments_dir) if args.segments_dir else None
    if seg_dir:
        seg_dir.mkdir(parents=True, exist_ok=True)

    try:
        for evt in client.synthesize_stream(
            text=args.text,
            lang=args.lang,
            voice=args.voice,
            engine=args.engine,
            max_chars=args.max_chars,
            speed=args.speed,
            ref_text=args.ref_text,
        ):
            wall = round(_time.monotonic() - t0, 2)
            d = evt["data"]
            if evt["event"] == "meta":
                pre_roll = d.get("pre_roll_sec", 0.0)
                if not args.quiet:
                    print(
                        f"[+{wall:>6.2f}s] meta: engine={d['engine']} sr={d['sample_rate']} "
                        f"segs={d['total_segments']} pre_roll={pre_roll}s "
                        f"safe_rtf={d['safe_rtf']} expected_dur={d.get('expected_total_dur_s')}s",
                        file=sys.stderr,
                    )
                sr = d["sample_rate"]
            elif evt["event"] == "audio":
                pcm = np.frombuffer(d["audio"], dtype=np.float32)
                audio_chunks.append(pcm)
                idx = d["chunk_idx"]
                if seg_dir:
                    sf.write(str(seg_dir / f"seg_{idx:03d}.wav"), pcm, sr)
                if not args.quiet:
                    print(
                        f"[+{wall:>6.2f}s] audio[{idx}] dur={d['duration_s']}s "
                        f"{'→ ' + str(seg_dir / f'seg_{idx:03d}.wav') if seg_dir else ''}",
                        file=sys.stderr,
                    )
            elif evt["event"] == "done":
                if not args.quiet:
                    print(
                        f"[+{wall:>6.2f}s] done: chunks={d['total_chunks']} "
                        f"total_dur={d['total_duration_s']}s wall={d['wall_s']}s",
                        file=sys.stderr,
                    )
                sr = d["sample_rate"]
            elif evt["event"] == "error":
                print(f"server error: {d.get('error', d)}", file=sys.stderr)
                return 1
    except Exception as e:
        print(f"stream failed: {e}", file=sys.stderr)
        return 1

    if not audio_chunks:
        print("no audio received", file=sys.stderr)
        return 1

    full = np.concatenate(audio_chunks)
    if args.out:
        sf.write(args.out, full, sr)
        if not args.quiet:
            print(
                f"[+{round(_time.monotonic() - t0, 2)}s] saved: {args.out}  "
                f"({round(len(full) / sr, 2)}s, {len(audio_chunks)} chunks)",
                file=sys.stderr,
            )
    elif not seg_dir:
        # No --out and no --segments-dir → stream raw wav bytes to stdout
        import io

        buf = io.BytesIO()
        sf.write(buf, full, sr, format="WAV")
        sys.stdout.buffer.write(buf.getvalue())
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
    res = client.explain_route(
        args.lang, multi_speaker=args.multi_speaker, prefer_fast=args.prefer_fast
    )
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
    p = argparse.ArgumentParser(
        prog="workshop-tts", description="Workshop TTS station CLI (v2 API)"
    )
    p.add_argument("--base-url", help="Override base URL (default uses port_registry)")
    p.add_argument("--json", action="store_true", help="Output JSON")
    sub = p.add_subparsers(dest="command")

    # Default subcommand: synthesize
    syn = sub.add_parser("synthesize", help="Synthesize speech (default)")
    syn.add_argument("--text", required=True)
    syn.add_argument("--lang", required=True, choices=["zh", "en", "ja", "ko", "auto"])
    syn.add_argument("--voice", default="master")
    syn.add_argument("--engine", default="auto")
    syn.add_argument(
        "--output",
        default="file",
        choices=["file", "buffer", "numpy", "tensor", "base64", "stream"],
    )
    syn.add_argument("--out", help="output path (FILE mode)")
    syn.add_argument("--sample-rate", type=int)
    syn.add_argument("--speed", type=float, default=1.0)
    syn.add_argument("--ref-text", help="reference transcript (qwen3tts zero-shot 必填)")
    syn.add_argument("--instruct", help="instruct prompt (cosyvoice)")

    # long subcommand — text segmented server-side, returns full concatenated wav
    lng = sub.add_parser("long", help="Synthesize long text (auto-segment + concat)")
    lng.add_argument("--text", required=True)
    lng.add_argument("--lang", required=True, choices=["zh", "en", "ja", "ko", "auto"])
    lng.add_argument("--voice", default="master")
    lng.add_argument("--engine", default="auto")
    lng.add_argument("--output", default="file", choices=["file", "buffer", "base64"])
    lng.add_argument("--out", help="output path (FILE mode)")
    lng.add_argument("--max-chars", type=int, help="override per-lang segment cap")
    lng.add_argument("--speed", type=float, default=1.0)
    lng.add_argument("--verbose", action="store_true", help="print per-segment durations")

    # stream subcommand — SSE chunks; CLI rebuilds wav locally
    strm = sub.add_parser("stream", help="SSE pseudo-streaming long text synthesis")
    strm.add_argument("--text", required=True)
    strm.add_argument("--lang", required=True, choices=["zh", "en", "ja", "ko", "auto"])
    strm.add_argument("--voice", default="master")
    strm.add_argument(
        "--engine",
        default="auto",
        help="engines with safe_rtf > 2.5 (e.g. indextts2) rejected — use `long` instead",
    )
    strm.add_argument("--max-chars", type=int, help="override per-lang segment cap")
    strm.add_argument("--speed", type=float, default=1.0)
    strm.add_argument("--ref-text")
    strm.add_argument("--out", help="write concatenated wav to this path")
    strm.add_argument("--segments-dir", help="also write each segment as seg_NNN.wav into this dir")
    strm.add_argument("--quiet", action="store_true", help="suppress per-event stderr progress")

    le = sub.add_parser("list-engines")  # noqa: F841
    lv = sub.add_parser("list-voices")  # noqa: F841

    rt = sub.add_parser("route", help="Explain auto-routing for given lang")
    rt.add_argument("--lang", required=True)
    rt.add_argument("--multi-speaker", action="store_true")
    rt.add_argument("--prefer-fast", action="store_true")

    sub.add_parser("healthcheck")

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
        elif args.command == "long":
            return cmd_long(args, client)
        elif args.command == "stream":
            return cmd_stream(args, client)
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
