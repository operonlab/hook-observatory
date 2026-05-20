#!/usr/bin/env python3
"""
voice_enhance.py — 對 voices/ 內的 reference voice 跑「降噪 + VAD 裁靜音 + 響度標準化」

Chain (ffmpeg filter graph)：
    afftdn (FFT 降噪) → silenceremove (VAD-like 靜音裁剪) → loudnorm (EBU R128 響度)
    最後 resample 到 16kHz mono（IndexTTS-2 / VibeVoice 偏好）

設計目標：每加一個新 voice 都跑一次本腳本，產出 `<voice_id>_enhanced.wav` 給 TTS
engine zero-shot voice clone 使用。原始 wav 與 _16k.wav 保留作為備份。

為何用 ffmpeg 而不用 audio-ops：
    audio-ops 的 DenoiseOp / VadTrimOp 依賴 sherpa-onnx，但本機 macOS 環境的
    sherpa-onnx wheel 缺失 libonnxruntime.1.24.4.dylib，重裝會影響 STT station。
    ffmpeg 內建 afftdn / silenceremove / loudnorm 三個 filter 效果近似，且
    零外部依賴、跨平台一致。

Usage:
    voice_enhance.py master              # 強化單個 voice
    voice_enhance.py --all               # 強化所有有 meta.yaml 的 voice
    voice_enhance.py --all --dry-run     # 只列出會處理哪些
    voice_enhance.py --input <path>      # 任意 wav，不查 meta

Behavior:
    - 載入 voice 的「主 variant」：優先 16kHz mono；其次 16k；最後 fallback <voice_id>.wav
    - 跑 ffmpeg chain
    - 輸出：voices/<voice_id>_enhanced.wav (16kHz mono, ~-16 LUFS, no leading/trailing silence)
    - 同步更新 meta.yaml 的 processed[] 為 applied: true（surgical sed-like 替換）
    - 印出 markdown manifest，提示 variants[] 該補的條目（手動 Edit 比腳本動 yaml 安全）

Dependencies:
    - ffmpeg + ffprobe（brew install ffmpeg）
    - pyyaml (stdlib 不含，但 ~/.local/bin/python3 已有)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

VOICES_DIR = Path.home() / "workshop" / "stations" / "tts" / "voices"
ENHANCED_SUFFIX = "_enhanced.wav"

# ── ffmpeg filter graph ──────────────────────────────────────────────────
# afftdn          — FFT denoiser, ~12dB reduction, -25dB noise floor
# highpass=80     — 砍 80Hz 以下低頻雜音（風、handling noise）
# silenceremove   — 頭尾各靜音 < -40dB 自動裁掉，留 100ms cushion
# loudnorm        — EBU R128, target -16 LUFS, true-peak -1.5dB
# aformat → mono 16k — TTS engine 偏好規格
FILTER_GRAPH = (
    "highpass=f=80,"
    "afftdn=nr=12:nf=-25,"
    "silenceremove="
    "start_periods=1:start_silence=0.05:start_threshold=-40dB:"
    "stop_periods=-1:stop_silence=0.10:stop_threshold=-40dB,"
    "loudnorm=I=-16:LRA=11:TP=-1.5,"
    "aformat=sample_fmts=s16:channel_layouts=mono:sample_rates=16000"
)


@dataclass
class EnhanceResult:
    voice_id: str
    input_file: str
    output_file: str
    input_sr: int
    output_sr: int
    input_duration_s: float
    output_duration_s: float
    ops_applied: list[str]
    error: str | None = None


def _ffprobe(path: Path) -> tuple[int, int, float]:
    """Return (sample_rate, channels, duration_s) via ffprobe."""
    r = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=sample_rate,channels,duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    parts = r.stdout.strip().split(",")
    return int(parts[0]), int(parts[1]), float(parts[2])


def _pick_main_variant(meta: dict, voice_id: str) -> str:
    """Pick main variant: prefer 16kHz mono, else any mono, else <voice_id>.wav."""
    variants = meta.get("variants") or []
    for v in variants:
        if v.get("sample_rate") == 16000 and v.get("channels") == 1:
            return v["file"]
    for v in variants:
        if v.get("channels") == 1:
            return v["file"]
    return f"{voice_id}.wav"


def enhance_file(input_path: Path, output_path: Path) -> list[str]:
    """Run ffmpeg filter graph. Returns list of ops applied."""
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-i",
        str(input_path),
        "-af",
        FILTER_GRAPH,
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return ["highpass80", "afftdn", "silenceremove_vad", "loudnorm", "resample16k_mono"]


def _patch_meta_applied(meta_path: Path, ops_mapping: dict[str, str]) -> None:
    """Surgical regex replace: turn `applied: false` → `applied: true` on lines
    whose `op:` field matches our meta-op names.

    ops_mapping maps the ffmpeg-side op to the meta-side op name:
        {"afftdn": "denoise", "silenceremove_vad": "vad_trim", "loudnorm": "normalize"}
    """
    text = meta_path.read_text(encoding="utf-8")
    new_text = text
    for meta_op_name in ops_mapping.values():
        pat = re.compile(
            rf"(op:\s*{re.escape(meta_op_name)}[^\n]*?)applied:\s*false",
            re.IGNORECASE,
        )
        new_text = pat.sub(r"\1applied: true", new_text)
    if new_text != text:
        meta_path.write_text(new_text, encoding="utf-8")


def enhance_voice(voice_id: str, dry_run: bool = False) -> EnhanceResult:
    meta_path = VOICES_DIR / f"{voice_id}.meta.yaml"
    if not meta_path.exists():
        return EnhanceResult(
            voice_id=voice_id,
            input_file="",
            output_file="",
            input_sr=0,
            output_sr=0,
            input_duration_s=0,
            output_duration_s=0,
            ops_applied=[],
            error="meta.yaml not found",
        )

    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    main_variant = _pick_main_variant(meta, voice_id)
    input_path = VOICES_DIR / main_variant
    output_path = VOICES_DIR / f"{voice_id}{ENHANCED_SUFFIX}"

    if not input_path.exists():
        return EnhanceResult(
            voice_id=voice_id,
            input_file=str(input_path),
            output_file=str(output_path),
            input_sr=0,
            output_sr=0,
            input_duration_s=0,
            output_duration_s=0,
            ops_applied=[],
            error="input wav not found",
        )

    in_sr, _in_ch, in_dur = _ffprobe(input_path)

    if dry_run:
        return EnhanceResult(
            voice_id=voice_id,
            input_file=main_variant,
            output_file=output_path.name,
            input_sr=in_sr,
            output_sr=16000,
            input_duration_s=in_dur,
            output_duration_s=0,
            ops_applied=["dry-run"],
            error=None,
        )

    try:
        ops = enhance_file(input_path, output_path)
    except subprocess.CalledProcessError as e:
        return EnhanceResult(
            voice_id=voice_id,
            input_file=main_variant,
            output_file=output_path.name,
            input_sr=in_sr,
            output_sr=0,
            input_duration_s=in_dur,
            output_duration_s=0,
            ops_applied=[],
            error=f"ffmpeg failed: {e.stderr[-200:]}",
        )

    out_sr, _out_ch, out_dur = _ffprobe(output_path)

    _patch_meta_applied(
        meta_path,
        ops_mapping={"afftdn": "denoise", "silenceremove_vad": "vad_trim", "loudnorm": "normalize"},
    )

    return EnhanceResult(
        voice_id=voice_id,
        input_file=main_variant,
        output_file=output_path.name,
        input_sr=in_sr,
        output_sr=out_sr,
        input_duration_s=in_dur,
        output_duration_s=out_dur,
        ops_applied=ops,
    )


def list_voices() -> list[str]:
    return sorted({p.name.replace(".meta.yaml", "") for p in VOICES_DIR.glob("*.meta.yaml")})


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("voice_id", nargs="?", help="single voice to enhance")
    parser.add_argument("--all", action="store_true", help="enhance all voices with meta.yaml")
    parser.add_argument("--dry-run", action="store_true", help="show what would happen")
    parser.add_argument("--json", action="store_true", help="emit JSON manifest")
    args = parser.parse_args()

    if args.all:
        voices = list_voices()
    elif args.voice_id:
        voices = [args.voice_id]
    else:
        parser.print_help()
        sys.exit(1)

    print(f"# voice_enhance — {len(voices)} voice(s)", file=sys.stderr)
    print("# chain: highpass80 → afftdn → silenceremove → loudnorm → 16k mono", file=sys.stderr)
    print("", file=sys.stderr)

    results: list[EnhanceResult] = []
    for vid in voices:
        print(f"  → {vid:10} ...", file=sys.stderr, end=" ", flush=True)
        r = enhance_voice(vid, dry_run=args.dry_run)
        results.append(r)
        if r.error:
            print(f"✗ {r.error}", file=sys.stderr)
        elif args.dry_run:
            print(f"would enhance: {r.input_file} → {r.output_file}", file=sys.stderr)
        else:
            shrink = r.output_duration_s - r.input_duration_s
            print(
                f"✓ {r.input_duration_s:.2f}s → {r.output_duration_s:.2f}s "
                f"({shrink:+.2f}s, sr {r.input_sr}→{r.output_sr})",
                file=sys.stderr,
            )

    if args.json:
        print(json.dumps([asdict(r) for r in results], indent=2, ensure_ascii=False))
        return

    print("\n## Enhance manifest\n")
    print("| voice_id | input | output | in_dur | out_dur | sr in→out | status |")
    print("|---|---|---|---|---|---|---|")
    for r in results:
        if r.error:
            print(f"| {r.voice_id} | {r.input_file or '—'} | — | — | — | — | ⚠️ {r.error} |")
        else:
            print(
                f"| {r.voice_id} | {r.input_file} | {r.output_file} "
                f"| {r.input_duration_s:.2f}s | {r.output_duration_s:.2f}s "
                f"| {r.input_sr} → {r.output_sr} | ✓ |"
            )

    print("\n## TODO（手動補到對應 meta.yaml 的 variants[]）\n")
    for r in results:
        if r.error:
            continue
        print(f"### {r.voice_id}.meta.yaml — append to variants[]:\n")
        print("```yaml")
        print(f"  - file: {r.output_file}")
        print(f"    sample_rate: {r.output_sr}")
        print("    channels: 1")
        print(f"    duration_s: {r.output_duration_s:.2f}")
        print("    preferred_engines: [indextts2_base, indextts2_jmica, vibevoice, index_tts]")
        print("    note: audio-ops enhanced (highpass + afftdn + silenceremove + loudnorm)")
        print("    enhanced: true")
        print("```\n")


if __name__ == "__main__":
    main()
