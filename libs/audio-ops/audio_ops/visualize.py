"""Audio visualisation operator — waveform + mel-spectrogram + bar charts.

Produces PNG artefacts for human-readable A/B audio comparison. Pairs with
SpeakerSimilarityOp when ranking voice-clone candidates: similarity gives the
number, visualize gives the picture.

Lazy dependency:
    Requires librosa + matplotlib. Install via:
        pip install workshop-audio-ops[visualize]
    Otherwise constructing VisualizeOp raises ImportError with a pointer.

Usage:
    # ── single audio: waveform + mel-spec stack ──
    VisualizeOp().render_one("clone.wav", out="clone.png")

    # ── A/B grid: multiple audios stacked, each row = one file ──
    VisualizeOp().compare(
        [("ref", "master.wav"), ("alpha=0.4", "alpha04.wav"), ...],
        out="grid.png",
        annotations={"alpha=0.4": "sim=0.841"},
    )

    # ── bar chart of similarity rankings ──
    VisualizeOp().rank_bar(
        {"alpha 0.2": 0.890, "alpha 0.4": 0.841, "alpha 0.6": 0.794},
        out="bar.png",
        thresholds=(0.85, 0.75),  # green / amber / red bands
    )
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from . import register

logger = logging.getLogger(__name__)


def _require_libs():
    try:
        import librosa
        import librosa.display
        import matplotlib.pyplot as plt
    except ImportError as e:
        raise ImportError(
            "VisualizeOp needs librosa + matplotlib. Install via:\n"
            "  pip install 'workshop-audio-ops[visualize]'\n"
            "or:\n"
            "  pip install librosa matplotlib"
        ) from e
    return librosa, plt


@register("visualize")
class VisualizeOp:
    """Render waveform + mel-spectrogram PNGs for human-readable A/B audio.

    Three top-level methods:
      - render_one(path, out=...)              one file, two-row stack
      - compare([(label, path), ...], out=...) grid: one row per file
      - rank_bar({label: score}, out=...)      sorted bar chart with bands
    """

    name = "visualize"
    input_keys = ("source_path",)
    output_keys = ("visualize_png",)

    # Default thresholds for rank_bar colour bands (match SpeakerSimilarityOp).
    DEFAULT_THRESHOLDS = (0.85, 0.75)

    def __init__(
        self,
        sr: int = 16000,
        n_mels: int = 80,
        fmax: int = 8000,
        dpi: int = 110,
    ):
        _require_libs()  # fail fast on missing deps
        self.sr = sr
        self.n_mels = n_mels
        self.fmax = fmax
        self.dpi = dpi

    # ── single-file render ────────────────────────────────────────

    def render_one(self, path: str | Path, out: str | Path) -> Path:
        """Render one wav as waveform + mel-spectrogram, write PNG to `out`."""
        librosa, plt = _require_libs()
        y, sr = librosa.load(str(path), sr=self.sr, mono=True)

        fig, axes = plt.subplots(2, 1, figsize=(10, 4))
        librosa.display.waveshow(y, sr=sr, ax=axes[0], color="steelblue")
        axes[0].set_title(str(Path(path).name), fontsize=10, loc="left")
        axes[0].set_xlabel("")

        mel = librosa.feature.melspectrogram(
            y=y, sr=sr, n_mels=self.n_mels, fmax=self.fmax
        )
        mel_db = librosa.power_to_db(mel, ref=np.max)
        librosa.display.specshow(
            mel_db, sr=sr, x_axis="time", y_axis="mel", ax=axes[1], fmax=self.fmax
        )
        axes[1].set_title("mel-spectrogram", fontsize=9, loc="left")
        plt.tight_layout()
        out_p = Path(out)
        plt.savefig(out_p, dpi=self.dpi, bbox_inches="tight")
        plt.close(fig)
        return out_p

    # ── grid: multiple files stacked ─────────────────────────────

    def compare(
        self,
        items: list[tuple[str, str | Path]],
        out: str | Path,
        annotations: dict[str, str] | None = None,
    ) -> Path:
        """Build a grid PNG: one row per audio, two columns (wave + mel).

        `items` is a list of (label, path) tuples; `annotations` optionally
        maps label → extra text appended to the row title (e.g. "sim=0.841").
        """
        librosa, plt = _require_libs()
        n = len(items)
        fig, axes = plt.subplots(n, 2, figsize=(14, 1.5 * n + 1), squeeze=False)
        annotations = annotations or {}
        max_dur = 0.0
        loaded = []
        for label, path in items:
            y, sr = librosa.load(str(path), sr=self.sr, mono=True)
            loaded.append((label, path, y, sr))
            max_dur = max(max_dur, len(y) / sr)

        for i, (label, path, y, sr) in enumerate(loaded):
            title = label
            if label in annotations:
                title = f"{label}  |  {annotations[label]}"
            librosa.display.waveshow(y, sr=sr, ax=axes[i][0], color="steelblue")
            axes[i][0].set_xlim(0, max_dur)
            axes[i][0].set_ylim(-1, 1)
            axes[i][0].set_xlabel("")
            axes[i][0].set_ylabel("")
            axes[i][0].set_title(title, fontsize=9, loc="left")

            mel = librosa.feature.melspectrogram(
                y=y, sr=sr, n_mels=self.n_mels, fmax=self.fmax
            )
            mel_db = librosa.power_to_db(mel, ref=np.max)
            librosa.display.specshow(
                mel_db, sr=sr, x_axis="time", y_axis="mel",
                ax=axes[i][1], fmax=self.fmax,
            )
            axes[i][1].set_xlabel("")
            axes[i][1].set_ylabel("")
            axes[i][1].set_title("mel-spectrogram", fontsize=9, loc="left")
        plt.tight_layout()
        out_p = Path(out)
        plt.savefig(out_p, dpi=self.dpi, bbox_inches="tight")
        plt.close(fig)
        return out_p

    # ── bar chart of similarities ─────────────────────────────────

    def rank_bar(
        self,
        scores: dict[str, float],
        out: str | Path,
        thresholds: tuple[float, float] = DEFAULT_THRESHOLDS,
        title: str = "Speaker-similarity ranking",
        xlabel: str = "cosine similarity",
    ) -> Path:
        """Horizontal bar chart sorted by score. Threshold bands colour bars:
        green > thresholds[0]; amber between; red < thresholds[1].
        """
        _, plt = _require_libs()
        items = sorted(scores.items(), key=lambda kv: -kv[1])
        labels = [k for k, _ in items]
        vals = [v for _, v in items]
        green, amber = thresholds

        colors = [
            "#2ca02c" if v > green else "#ff9800" if v > amber else "#d62728"
            for v in vals
        ]
        fig, ax = plt.subplots(figsize=(10, max(4, 0.4 * len(items))))
        bars = ax.barh(range(len(labels)), vals, color=colors)
        ax.set_yticks(range(len(labels)))
        ax.set_yticklabels(labels)
        ax.set_xlim(0, 1.0)
        ax.axvline(green, color="gray", linestyle="--", linewidth=1, alpha=0.5)
        ax.axvline(amber, color="gray", linestyle=":", linewidth=1, alpha=0.5)
        ax.set_xlabel(xlabel)
        ax.set_title(f"{title} (green > {green} threshold)")
        for bar, v in zip(bars, vals):
            ax.text(
                v + 0.005, bar.get_y() + bar.get_height() / 2,
                f"{v:.3f}", va="center", fontsize=9,
            )
        ax.invert_yaxis()
        plt.tight_layout()
        out_p = Path(out)
        plt.savefig(out_p, dpi=120, bbox_inches="tight")
        plt.close(fig)
        return out_p

    # ── pipeline form ─────────────────────────────────────────────

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Pipeline mode: render the current ctx['source_path'] to a PNG
        sibling and write its path to ctx['visualize_png'].
        """
        src = ctx.get("source_path")
        if src is None:
            raise ValueError("VisualizeOp pipeline mode expects ctx['source_path']")
        src_p = Path(src)
        out_p = src_p.with_suffix(".vis.png")
        self.render_one(src_p, out_p)
        ctx["visualize_png"] = str(out_p)
        return ctx
