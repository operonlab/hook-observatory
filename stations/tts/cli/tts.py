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


def _build_engine_specific(args) -> dict | None:
    """Common --emotion* / --instruct / --ref-text → engine_specific dict.

    Subcommands attach a subset of these flags via `_add_engine_specific_args`;
    missing attributes are treated as None so this helper is safe to call
    from any cmd_*.
    """
    es: dict = {}
    ref_text = getattr(args, "ref_text", None)
    if ref_text:
        es["ref_text"] = ref_text
    instruct = getattr(args, "instruct", None)
    if instruct:
        es["instruct"] = instruct

    # IndexTTS-2 emotion — at most one of preset / text / audio / vector.
    emo: dict = {}
    preset = getattr(args, "emotion", None)
    if preset:
        emo["preset"] = preset
    emo_text = getattr(args, "emotion_text", None)
    if emo_text:
        emo["text"] = emo_text
    emo_audio = getattr(args, "emotion_audio", None)
    if emo_audio:
        emo["audio"] = emo_audio
    emo_vector = getattr(args, "emotion_vector", None)
    if emo_vector:
        try:
            vec = [float(x) for x in emo_vector.split(",")]
        except ValueError as e:
            raise SystemExit(f"--emotion-vector must be 8 floats separated by commas: {e}")
        if len(vec) != 8:
            raise SystemExit(f"--emotion-vector must be 8-dim, got {len(vec)}")
        emo["vector"] = vec
    if emo:
        alpha = getattr(args, "emotion_alpha", None)
        # Default alpha = TTSClient.DEFAULT_EMOTION_ALPHA (0.4) — speaker-
        # similarity sweep showed voice identity collapses above ~0.6 (see
        # outputs/tts-emotion-smoke/similarity_bar.png). Explicit
        # --emotion-alpha 1.0 still works for callers who want max strength.
        if alpha is None:
            alpha = TTSClient.DEFAULT_EMOTION_ALPHA
        emo["alpha"] = float(alpha)
        es["emotion"] = emo
    return es or None


def cmd_synthesize(args, client: TTSClient) -> int:
    engine_specific = _build_engine_specific(args)

    res = client.synthesize_v2(
        text=args.text,
        lang=args.lang,
        voice=args.voice,
        engine=args.engine,
        output=args.output,
        out_path=args.out,
        target_sample_rate=args.sample_rate,
        speed=args.speed,
        engine_specific=engine_specific,
        mode=getattr(args, "mode", None),
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
        mode=getattr(args, "mode", None),
        engine_specific=_build_engine_specific(args),
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
            mode=getattr(args, "mode", None),
            engine_specific=_build_engine_specific(args),
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


def cmd_podcast(args, client: TTSClient) -> int:
    """Multi-speaker podcast: 'Speaker N:' script + voices map → single wav."""
    # Parse --voices "1=master,2=xinran"
    voices: dict[str, str] = {}
    for pair in (args.voices or "").split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            print(f"bad --voices entry: {pair!r}, expected 'N=voice_id'", file=sys.stderr)
            return 2
        k, v = pair.split("=", 1)
        voices[k.strip()] = v.strip()
    if not voices:
        print("--voices required, e.g. --voices '1=master,2=xinran'", file=sys.stderr)
        return 2

    if args.script_file:
        with open(args.script_file, encoding="utf-8") as f:
            script = f.read()
    elif args.script:
        # Convert literal "\n" sequences to real newlines so shell users can
        # pass a multi-line script in a single --script argument.
        script = args.script.replace("\\n", "\n")
    else:
        print("--script or --script-file required", file=sys.stderr)
        return 2

    res = client.synthesize_podcast(
        script=script,
        voices=voices,
        lang=args.lang,
        engine=args.engine,
        output="base64",
        speed=args.speed,
        mode=getattr(args, "mode", None),
        engine_specific=_build_engine_specific(args),
    )
    audio_b64 = res.get("audio_base64") or res.get("audio_bytes_b64", "")
    if not audio_b64:
        print(
            f"server returned no audio: {json.dumps(res, ensure_ascii=False)[:200]}",
            file=sys.stderr,
        )
        return 1
    audio_bytes = base64.b64decode(audio_b64)
    if not args.out:
        import tempfile

        args.out = tempfile.mktemp(suffix=".wav", prefix=f"tts_podcast_{res.get('engine', 'x')}_")
    with open(args.out, "wb") as f:
        f.write(audio_bytes)

    if args.json:
        print(json.dumps({**res, "audio_path": args.out}, ensure_ascii=False, indent=2))
    else:
        eng = res.get("engine", "?")
        dur = res.get("duration_s", "?")
        segs = res.get("segments", "?")
        speakers = res.get("seg_speakers", [])
        print(f"[{eng}] podcast: {dur}s in {segs} seg(s), speakers={speakers}  →  {args.out}")
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
        args.lang,
        multi_speaker=args.multi_speaker,
        prefer_fast=args.prefer_fast,
        mode=getattr(args, "mode", None),
    )
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(f"mode:    {res.get('mode')}")
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


_EMOTION_CHOICES = TTSClient.EMOTION_NAMES


def _add_engine_specific_args(
    sp: argparse.ArgumentParser, *, with_instruct: bool = True, with_ref_text: bool = True
) -> None:
    """Attach the engine_specific flag set to a subparser.

    Subcommands that already declare --ref-text / --instruct themselves skip
    the matching part via the with_* flags.
    """
    if with_ref_text:
        sp.add_argument("--ref-text", help="reference transcript (qwen3tts zero-shot 必填)")
    if with_instruct:
        sp.add_argument(
            "--instruct",
            help="CosyVoice instruct2 natural-language directive (overrides zero_shot path)",
        )
    sp.add_argument(
        "--emotion",
        choices=_EMOTION_CHOICES,
        help="IndexTTS-2 emotion preset (mutually exclusive with --emotion-text/-audio/-vector)",
    )
    sp.add_argument(
        "--emotion-text",
        help="IndexTTS-2 emotion via natural-language description (routes through QwenEmotion)",
    )
    sp.add_argument(
        "--emotion-audio",
        help="IndexTTS-2 emotion via reference wav path",
    )
    sp.add_argument(
        "--emotion-vector",
        help="IndexTTS-2 emotion via raw 8-dim float CSV (e.g. '1,0,0,0,0,0,0,0')",
    )
    sp.add_argument(
        "--emotion-alpha",
        type=float,
        default=None,
        help="Emotion intensity 0.0-1.0 (default 1.0)",
    )


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
    _add_engine_specific_args(syn)
    syn.add_argument(
        "--mode",
        choices=["quality", "live"],
        help="routing preset (quality=indextts default / live=cosyvoice sub-realtime); only applies when --engine=auto",
    )

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
    _add_engine_specific_args(lng)
    lng.add_argument("--mode", choices=["quality", "live"], help="routing preset")

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
    strm.add_argument("--out", help="write concatenated wav to this path")
    strm.add_argument("--segments-dir", help="also write each segment as seg_NNN.wav into this dir")
    strm.add_argument("--quiet", action="store_true", help="suppress per-event stderr progress")
    _add_engine_specific_args(strm)
    strm.add_argument("--mode", choices=["quality", "live"], help="routing preset")

    # podcast subcommand — multi-speaker conversational synthesis
    pod = sub.add_parser("podcast", help="Multi-speaker podcast (Speaker N: lines)")
    src = pod.add_mutually_exclusive_group(required=True)
    src.add_argument("--script", help="Inline script with 'Speaker N: text' lines")
    src.add_argument("--script-file", help="Path to script file")
    pod.add_argument(
        "--voices",
        required=True,
        help="Speaker-id → voice_id map, e.g. '1=master,2=xinran'",
    )
    pod.add_argument("--lang", required=True, choices=["zh", "en", "ja", "ko"])
    pod.add_argument("--engine", default="auto")
    pod.add_argument("--out", help="output wav path")
    pod.add_argument("--speed", type=float, default=1.0)
    # Podcast emotion/instruct applies whole-script. Per-speaker override is
    # available via the SDK (engine_specific_by_speaker) and the /v2 endpoint
    # body; CLI keeps the surface flat for now.
    _add_engine_specific_args(pod, with_ref_text=False)
    pod.add_argument("--mode", choices=["quality", "live"], help="routing preset")

    le = sub.add_parser("list-engines")  # noqa: F841
    lv = sub.add_parser("list-voices")  # noqa: F841

    rt = sub.add_parser("route", help="Explain auto-routing for given lang")
    rt.add_argument("--lang", required=True)
    rt.add_argument("--multi-speaker", action="store_true")
    rt.add_argument("--prefer-fast", action="store_true")
    rt.add_argument("--mode", choices=["quality", "live"])

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
    p.add_argument("--emotion", choices=_EMOTION_CHOICES, help=argparse.SUPPRESS)
    p.add_argument("--emotion-text", help=argparse.SUPPRESS)
    p.add_argument("--emotion-audio", help=argparse.SUPPRESS)
    p.add_argument("--emotion-vector", help=argparse.SUPPRESS)
    p.add_argument("--emotion-alpha", type=float, default=None, help=argparse.SUPPRESS)
    p.add_argument("--mode", choices=["quality", "live"], help=argparse.SUPPRESS)
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
        elif args.command == "podcast":
            return cmd_podcast(args, client)
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
