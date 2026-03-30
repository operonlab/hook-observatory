"""Audio quality analysis operator — generates metrics + three-view PNG.

Detects: clipping, silence, noise, formant absence, pitch anomalies.
Returns pass/fail verdict with detailed metrics.

Usage:
    AudioPipe.from_file("out.wav").pipe(AnalyzeOp()).execute()
    # ctx["analysis"] = {metrics dict}
    # ctx["analysis_png"] = "/path/to/three_view.png"
    # ctx["analysis_pass"] = True/False
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from . import register

logger = logging.getLogger(__name__)

# ── Thresholds for pass/fail ──

THRESHOLDS = {
    "peak_max": 0.99,  # clipping if peak >= this
    "peak_min": 0.05,  # too quiet if peak < this
    "rms_min": 0.005,  # essentially silent
    "rms_max": 0.5,  # suspiciously loud (square wave / noise)
    "silence_ratio_max": 0.8,  # >80% silence = bad
    "snr_min": 5.0,  # <5dB SNR = noisy
    "f0_min": 50.0,  # below 50Hz = abnormal for speech
    "f0_max": 500.0,  # above 500Hz = abnormal for speech
    "formant_energy_min": -60.0,  # formant band too weak
}


def _compute_metrics(audio: np.ndarray, sr: int) -> dict:
    """Compute all audio quality metrics."""
    metrics: dict[str, Any] = {}

    # ── Basic amplitude ──
    metrics["sample_rate"] = sr
    metrics["duration"] = len(audio) / sr if len(audio) > 0 else 0.0

    if len(audio) == 0:
        return {
            **metrics,
            "peak": 0,
            "rms": 0,
            "peak_db": -100,
            "rms_db": -100,
            "crest_factor": 0,
            "clipped_samples": 0,
            "clipped_ratio": 0,
            "silence_ratio": 1.0,
            "snr_db": 0,
            "f0_estimate": 0,
            "spectral_centroid": 0,
            "formant_energy_db": -100,
            "hf_energy_ratio": 0,
            "spectral_flatness": 0,
        }

    metrics["peak"] = float(np.max(np.abs(audio)))
    metrics["rms"] = float(np.sqrt(np.mean(audio**2)))
    metrics["peak_db"] = float(20 * np.log10(metrics["peak"] + 1e-10))
    metrics["rms_db"] = float(20 * np.log10(metrics["rms"] + 1e-10))
    metrics["crest_factor"] = float(metrics["peak"] / (metrics["rms"] + 1e-10))

    # ── Clipping detection ──
    clip_samples = int(np.sum(np.abs(audio) >= 0.999))
    metrics["clipped_samples"] = clip_samples
    metrics["clipped_ratio"] = clip_samples / len(audio)

    # ── Silence ratio (below -40dB) ──
    frame_len = int(sr * 0.025)  # 25ms frames
    hop = int(sr * 0.010)  # 10ms hop
    num_frames = max(1, (len(audio) - frame_len) // hop)
    silent_frames = 0
    for i in range(num_frames):
        frame = audio[i * hop : i * hop + frame_len]
        frame_rms = np.sqrt(np.mean(frame**2))
        if frame_rms < 0.01:  # ~-40dB
            silent_frames += 1
    metrics["silence_ratio"] = silent_frames / num_frames

    # ── SNR estimate (signal vs noise floor) ──
    sorted_rms = []
    for i in range(num_frames):
        frame = audio[i * hop : i * hop + frame_len]
        sorted_rms.append(np.sqrt(np.mean(frame**2)))
    sorted_rms.sort()
    if len(sorted_rms) > 10:
        noise_floor = np.mean(sorted_rms[: len(sorted_rms) // 10]) + 1e-10
        signal_level = np.mean(sorted_rms[-len(sorted_rms) // 4 :]) + 1e-10
        metrics["snr_db"] = float(20 * np.log10(signal_level / noise_floor))
    else:
        metrics["snr_db"] = 0.0

    # ── F0 (pitch) estimate via autocorrelation ──
    # Use 1 second of voiced audio
    seg = audio[: min(sr * 2, len(audio))]
    # Simple autocorrelation pitch detection
    min_lag = int(sr / 500)  # 500Hz max
    max_lag = int(sr / 50)  # 50Hz min
    if len(seg) > max_lag * 2:
        corr = np.correlate(seg[: max_lag * 2], seg[: max_lag * 2], mode="full")
        corr = corr[len(corr) // 2 :]
        if max_lag < len(corr):
            search = corr[min_lag:max_lag]
            if len(search) > 0:
                peak_idx = np.argmax(search) + min_lag
                metrics["f0_estimate"] = float(sr / peak_idx)
            else:
                metrics["f0_estimate"] = 0.0
        else:
            metrics["f0_estimate"] = 0.0
    else:
        metrics["f0_estimate"] = 0.0

    # ── Spectral metrics ──
    n_fft = min(2048, len(audio))
    if len(audio) >= n_fft:
        spectrum = np.abs(np.fft.rfft(audio[:n_fft]))
        freqs = np.fft.rfftfreq(n_fft, 1 / sr)

        # Spectral centroid
        power = spectrum**2
        metrics["spectral_centroid"] = float(np.sum(freqs * power) / (np.sum(power) + 1e-10))

        # Formant energy bands (speech: 300-3400Hz)
        formant_mask = (freqs >= 300) & (freqs <= 3400)
        if np.any(formant_mask):
            formant_power = np.mean(power[formant_mask])
            metrics["formant_energy_db"] = float(10 * np.log10(formant_power + 1e-10))
        else:
            metrics["formant_energy_db"] = -100.0

        # High-frequency energy ratio (>4kHz, indicates noise or artifacts)
        hf_mask = freqs > 4000
        total_power = np.sum(power) + 1e-10
        metrics["hf_energy_ratio"] = float(np.sum(power[hf_mask]) / total_power)

        # Spectral flatness (1.0 = white noise, 0.0 = tonal)
        log_spec = np.log(spectrum + 1e-10)
        metrics["spectral_flatness"] = float(
            np.exp(np.mean(log_spec)) / (np.mean(spectrum) + 1e-10)
        )
    else:
        metrics["spectral_centroid"] = 0.0
        metrics["formant_energy_db"] = -100.0
        metrics["hf_energy_ratio"] = 0.0
        metrics["spectral_flatness"] = 0.0

    return metrics


def _check_pass(metrics: dict) -> tuple[bool, list[str]]:
    """Check metrics against thresholds. Returns (pass, issues)."""
    issues = []
    T = THRESHOLDS

    if metrics["peak"] >= T["peak_max"]:
        issues.append(f"CLIPPING: peak={metrics['peak']:.3f} (>={T['peak_max']})")
    if metrics["peak"] < T["peak_min"]:
        issues.append(f"TOO_QUIET: peak={metrics['peak']:.3f} (<{T['peak_min']})")
    if metrics["rms"] < T["rms_min"]:
        issues.append(f"SILENT: rms={metrics['rms']:.4f} (<{T['rms_min']})")
    if metrics["rms"] > T["rms_max"]:
        issues.append(f"SQUARE_WAVE: rms={metrics['rms']:.4f} (>{T['rms_max']})")
    if metrics["silence_ratio"] > T["silence_ratio_max"]:
        issues.append(
            f"MOSTLY_SILENT: {metrics['silence_ratio']:.0%} (>{T['silence_ratio_max']:.0%})"
        )
    if metrics["snr_db"] < T["snr_min"]:
        issues.append(f"NOISY: snr={metrics['snr_db']:.1f}dB (<{T['snr_min']}dB)")
    if 0 < metrics["f0_estimate"] < T["f0_min"]:
        issues.append(f"F0_LOW: {metrics['f0_estimate']:.0f}Hz (<{T['f0_min']}Hz)")
    if metrics["f0_estimate"] > T["f0_max"]:
        issues.append(f"F0_HIGH: {metrics['f0_estimate']:.0f}Hz (>{T['f0_max']}Hz)")
    if metrics["formant_energy_db"] < T["formant_energy_min"]:
        issues.append(
            f"NO_FORMANTS: {metrics['formant_energy_db']:.0f}dB (<{T['formant_energy_min']}dB)"
        )
    if metrics["spectral_flatness"] > 0.8:
        issues.append(f"WHITE_NOISE: flatness={metrics['spectral_flatness']:.2f}")
    if metrics["clipped_ratio"] > 0.01:
        issues.append(f"HEAVY_CLIPPING: {metrics['clipped_ratio']:.1%} samples clipped")

    return len(issues) == 0, issues


def _generate_three_view(
    audio: np.ndarray,
    sr: int,
    metrics: dict,
    passed: bool,
    issues: list[str],
    label: str = "",
    output_path: str | None = None,
) -> str:
    """Generate three-view PNG (waveform + spectrogram + power spectrum)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(18, 4))
    t = np.arange(len(audio)) / sr
    status = "PASS" if passed else "FAIL"
    color = "#4CAF50" if passed else "#F44336"

    # ── Waveform ──
    axes[0].plot(t, audio, linewidth=0.3, color="#2196F3")
    axes[0].set_title("Waveform", fontsize=11)
    axes[0].set_ylim(-1, 1)
    axes[0].set_xlabel("Time (s)")
    axes[0].set_ylabel("Amplitude")
    info = (
        f"Peak={metrics['peak']:.3f} RMS={metrics['rms']:.4f}\n"
        f"SNR={metrics['snr_db']:.1f}dB Silence={metrics['silence_ratio']:.0%}"
    )
    axes[0].text(
        0.02,
        0.95,
        info,
        transform=axes[0].transAxes,
        fontsize=7,
        va="top",
        bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5),
    )

    # ── Spectrogram ──
    n_fft = 2048
    hop = 512
    if len(audio) > n_fft:
        padded = np.pad(audio, (0, n_fft - len(audio) % hop if len(audio) % hop else 0))
        frames = np.lib.stride_tricks.sliding_window_view(padded, n_fft)[::hop]
        frames = frames * np.hanning(n_fft)
        spec_db = 20 * np.log10(np.abs(np.fft.rfft(frames, axis=1)).T + 1e-10)
        axes[1].imshow(
            spec_db,
            aspect="auto",
            origin="lower",
            cmap="magma",
            extent=[0, len(audio) / sr, 0, sr / 2],
            vmin=-80,
            vmax=0,
        )
        axes[1].set_ylim(0, min(sr / 2, 8000))
    axes[1].set_title("Spectrogram", fontsize=11)
    axes[1].set_xlabel("Time (s)")
    axes[1].set_ylabel("Freq (Hz)")

    # ── Power Spectrum ──
    seg = audio[: min(sr, len(audio))]
    ps = np.abs(np.fft.rfft(seg))
    freqs = np.fft.rfftfreq(len(seg), 1 / sr)
    lim = min(4000, len(freqs))
    axes[2].plot(freqs[:lim], 20 * np.log10(ps[:lim] + 1e-10), linewidth=0.5, color="#FF5722")
    axes[2].set_title("Power Spectrum (1st sec)", fontsize=11)
    axes[2].set_xlabel("Freq (Hz)")
    axes[2].set_xlim(0, 4000)
    info2 = (
        f"F0≈{metrics['f0_estimate']:.0f}Hz Centroid={metrics['spectral_centroid']:.0f}Hz\n"
        f"Formant={metrics['formant_energy_db']:.0f}dB Flatness={metrics['spectral_flatness']:.2f}"
    )
    axes[2].text(
        0.02,
        0.95,
        info2,
        transform=axes[2].transAxes,
        fontsize=7,
        va="top",
        bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5),
    )

    title = f"[{status}] {label}" if label else f"[{status}]"
    if issues:
        title += f"  —  {', '.join(issues[:3])}"
    fig.suptitle(title, fontsize=12, color=color, fontweight="bold")
    plt.tight_layout(rect=[0, 0, 1, 0.94])

    if not output_path:
        output_path = tempfile.mktemp(suffix=".png", prefix="audio_analysis_")
    plt.savefig(output_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return output_path


@register("analyze")
class AnalyzeOp:
    """Audio quality analysis — metrics + three-view PNG + pass/fail verdict.

    Results stored in ctx:
        ctx["analysis"]      — dict of all metrics
        ctx["analysis_pass"] — bool (True = healthy audio)
        ctx["analysis_issues"] — list of issue strings (empty if pass)
        ctx["analysis_png"]  — path to three-view PNG (if generate_png=True)
    """

    name = "analyze"
    input_keys = ("audio",)
    output_keys = ("analysis", "analysis_pass", "analysis_issues", "analysis_png")

    def __init__(self, generate_png: bool = True, output_dir: str | None = None, label: str = ""):
        self.generate_png = generate_png
        self.output_dir = output_dir
        self.label = label

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        audio = ctx["audio"]
        sr = ctx["sample_rate"]

        metrics = _compute_metrics(audio, sr)
        passed, issues = _check_pass(metrics)

        ctx["analysis"] = metrics
        ctx["analysis_pass"] = passed
        ctx["analysis_issues"] = issues

        status = "PASS" if passed else "FAIL"
        label = self.label or ctx.get("source_path", "")
        logger.info(
            "Analyze [%s] %s: peak=%.3f rms=%.4f snr=%.1fdB",
            status,
            label,
            metrics["peak"],
            metrics["rms"],
            metrics["snr_db"],
        )
        if issues:
            for issue in issues:
                logger.warning("  ⚠ %s", issue)

        if self.generate_png:
            png_dir = self.output_dir or tempfile.gettempdir()
            Path(png_dir).mkdir(parents=True, exist_ok=True)
            safe_label = Path(label).stem if label else "audio"
            png_path = str(Path(png_dir) / f"analysis_{safe_label}.png")
            ctx["analysis_png"] = _generate_three_view(
                audio,
                sr,
                metrics,
                passed,
                issues,
                label=label,
                output_path=png_path,
            )

        return ctx
