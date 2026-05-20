"""Speaker-similarity operator — cosine of d-vector embeddings.

Wraps Resemblyzer's VoiceEncoder (ECAPA-TDNN family) to give an objective
voice-clone fidelity number in [0, 1]. A score of 1.0 means same speaker,
~0.85 is the conventional "same speaker" threshold for d-vector similarity,
and ~0.75 is the floor where voice identity has clearly drifted.

Typical use: TTS clone regression, voice-catalogue dedup audit, podcast
speaker-consistency check.

Lazy dependency:
    Requires resemblyzer + scipy. Install via:
        pip install workshop-audio-ops[similarity]
    Otherwise constructing SpeakerSimilarityOp raises ImportError with a
    pointer to the extras.

Usage:
    # ── score one clone against a reference ──
    op = SpeakerSimilarityOp(ref="master.wav")
    score = op.score("clone.wav")          # 0.0 - 1.0
    # ── batch ──
    rankings = op.batch({
        "alpha_0.2": "alpha_sweep_happy_a02.wav",
        "alpha_0.4": "alpha_sweep_happy_a04.wav",
        "alpha_0.6": "alpha_sweep_happy_a06.wav",
    })
    # → {"alpha_0.2": 0.890, "alpha_0.4": 0.841, "alpha_0.6": 0.794}
    # ── pipeline form ──
    AudioPipe.from_file("clone.wav").pipe(
        SpeakerSimilarityOp(ref="master.wav"),
    ).execute()
    # ctx["speaker_similarity"] = 0.84, ctx["speaker_similarity_pass"] = True
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from . import register

logger = logging.getLogger(__name__)


def _require_resemblyzer():
    """Lazy import — surface a clear error when extras aren't installed."""
    try:
        from resemblyzer import VoiceEncoder, preprocess_wav
    except ImportError as e:
        raise ImportError(
            "SpeakerSimilarityOp needs resemblyzer + scipy. Install via:\n"
            "  pip install 'workshop-audio-ops[similarity]'\n"
            "or:\n"
            "  pip install resemblyzer scipy"
        ) from e
    return VoiceEncoder, preprocess_wav


# Conventional thresholds for d-vector cosine. Tuned for ECAPA-TDNN family;
# these are reasonable defaults but can be overridden per-call.
SIMILARITY_THRESHOLDS = {
    "same_speaker": 0.85,  # > here ⇒ confidently same person
    "close": 0.75,         # 0.75-0.85: recognisable but drifting
    # below 0.75 ⇒ clearly different speaker
}


@register("speaker_similarity")
class SpeakerSimilarityOp:
    """Cosine similarity of d-vector embeddings against a reference wav.

    Encoder model is cached on the class — the first construction loads it
    (~80MB download to ~/.cache on first use); subsequent instances reuse it.
    """

    name = "speaker_similarity"
    input_keys = ("source_path",)
    output_keys = ("speaker_similarity",)

    _encoder: ClassVar[Any] = None  # shared VoiceEncoder

    def __init__(
        self,
        ref: str | Path | np.ndarray,
        device: str = "cpu",
        threshold_same: float = SIMILARITY_THRESHOLDS["same_speaker"],
        threshold_close: float = SIMILARITY_THRESHOLDS["close"],
    ):
        VoiceEncoder, preprocess_wav = _require_resemblyzer()
        if SpeakerSimilarityOp._encoder is None:
            SpeakerSimilarityOp._encoder = VoiceEncoder(device=device, verbose=False)
        self._preprocess = preprocess_wav
        self.threshold_same = threshold_same
        self.threshold_close = threshold_close
        self._ref_embed = self._embed(ref)

    # ── core API ──────────────────────────────────────────────────

    def _embed(self, src: str | Path | np.ndarray) -> np.ndarray:
        """Run the encoder on a wav path or a numpy array.

        Numpy arrays are passed through preprocess_wav for VAD + resample to
        the 16k mono expected by Resemblyzer.
        """
        if isinstance(src, (str, Path)):
            wav = self._preprocess(str(src))
        else:
            wav = self._preprocess(np.asarray(src, dtype=np.float32))
        return SpeakerSimilarityOp._encoder.embed_utterance(wav)

    def score(self, candidate: str | Path | np.ndarray) -> float:
        """Cosine similarity ∈ [0, 1] between candidate and the configured ref."""
        cand_embed = self._embed(candidate)
        return self._cosine(self._ref_embed, cand_embed)

    def batch(
        self, candidates: dict[str, str | Path | np.ndarray]
    ) -> dict[str, float]:
        """Score many candidates against the same ref; returns label → cosine."""
        return {label: self.score(path) for label, path in candidates.items()}

    def verdict(self, score: float) -> str:
        """Map a cosine score to a human label."""
        if score >= self.threshold_same:
            return "same_speaker"
        if score >= self.threshold_close:
            return "close"
        return "drift"

    @staticmethod
    def _cosine(a: np.ndarray, b: np.ndarray) -> float:
        denom = float(np.linalg.norm(a) * np.linalg.norm(b))
        if denom == 0:
            return 0.0
        return float(np.dot(a, b) / denom)

    # ── pipeline form (AudioPipe-compatible) ──────────────────────

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Pipeline mode: reads ctx['source_path'] or ctx['audio'], writes
        ctx['speaker_similarity'] (float) + ctx['speaker_similarity_pass'] (bool).
        """
        src = ctx.get("source_path") or ctx.get("audio")
        if src is None:
            raise ValueError(
                "SpeakerSimilarityOp expects ctx['source_path'] or ctx['audio']"
            )
        score = self.score(src)
        ctx["speaker_similarity"] = score
        ctx["speaker_similarity_pass"] = score >= self.threshold_close
        ctx["speaker_similarity_verdict"] = self.verdict(score)
        logger.info(
            "speaker_similarity=%.4f verdict=%s",
            score,
            ctx["speaker_similarity_verdict"],
        )
        return ctx
