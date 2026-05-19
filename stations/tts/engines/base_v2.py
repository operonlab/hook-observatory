"""v2 Engine ABC — unified OutputMode + capability + lazy lifecycle.

新版 v3 系列 engine（cosyvoice_v3_native/_vllm, indextts2_base/_jmica,
vibevoice, qwen3tts_gpu）統一走這個 ABC。舊版 Mac 引擎（edge/apple/...）
仍走 engines/__init__.py 的 Protocol（不破 backward compat）。

Engine 子類只需實作 _synthesize_raw() → (numpy float32, sr)，
其他 OutputMode 轉換（file/buffer/numpy/tensor/base64/stream）由共用層處理。
"""

from __future__ import annotations

import base64
import io
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)


class OutputMode(str, Enum):
    FILE = "file"
    BUFFER = "buffer"
    NUMPY = "numpy"
    TENSOR = "tensor"
    BASE64 = "base64"
    STREAM = "stream"


@dataclass
class EngineCapability:
    name: str
    languages: list[str]
    multi_speaker: bool
    rtf_typical: float
    vram_mb: int
    needs_wsl: bool
    needs_gpu: bool
    ref_duration_range: tuple[int, int]
    needs_ref_text: bool
    supported_outputs: list[OutputMode]
    sample_rate: int
    notes: str = ""


@dataclass
class SynthesizeRequest:
    text: str
    lang: str
    voice_id: str = "master"
    output: OutputMode = OutputMode.FILE
    output_path: Optional[str] = None
    target_sample_rate: Optional[int] = None
    speed: float = 1.0
    engine_specific: dict[str, Any] = field(default_factory=dict)


@dataclass
class SynthesizeResult:
    duration_s: float
    sample_rate: int
    rtf: float
    engine: str
    output_mode: OutputMode
    audio_path: Optional[str] = None
    audio_bytes: Optional[bytes] = None
    audio_base64: Optional[str] = None
    audio_numpy: Optional[np.ndarray] = None
    audio_tensor: Optional[Any] = None
    audio_stream: Optional[Iterator[bytes]] = None

    def to_jsonable(self) -> dict:
        """For HTTP / MCP wire format — drop non-JSON fields, b64-wrap bytes."""
        d: dict[str, Any] = {
            "duration_s": round(self.duration_s, 3),
            "sample_rate": self.sample_rate,
            "rtf": round(self.rtf, 4),
            "engine": self.engine,
            "output_mode": self.output_mode.value,
        }
        if self.audio_path:
            d["audio_path"] = self.audio_path
        if self.audio_base64:
            d["audio_base64"] = self.audio_base64
        if self.audio_bytes:
            d["audio_bytes_b64"] = base64.b64encode(self.audio_bytes).decode()
        return d


def _resample(audio: np.ndarray, src_sr: int, tgt_sr: int) -> np.ndarray:
    """Soft-dependency resample. Falls back to scipy if librosa missing."""
    if src_sr == tgt_sr:
        return audio
    try:
        import librosa
        return librosa.resample(audio, orig_sr=src_sr, target_sr=tgt_sr)
    except ImportError:
        from scipy.signal import resample_poly
        from math import gcd
        g = gcd(src_sr, tgt_sr)
        return resample_poly(audio, tgt_sr // g, src_sr // g).astype(np.float32)


class TTSEngineV2(ABC):
    """Subclasses implement _synthesize_raw() + capability() + healthcheck().

    The shared synthesize() wrapper handles OutputMode conversion + timing + resample.
    """

    @abstractmethod
    def capability(self) -> EngineCapability: ...

    @abstractmethod
    def _synthesize_raw(self, req: SynthesizeRequest) -> tuple[np.ndarray, int]:
        """Return (audio float32 mono in [-1,1], sample_rate)."""

    def synthesize(self, req: SynthesizeRequest) -> SynthesizeResult:
        cap = self.capability()
        if cap.needs_ref_text and not req.engine_specific.get("ref_text"):
            logger.warning("%s: ref_text not provided, may degrade", cap.name)

        if req.output not in cap.supported_outputs:
            raise ValueError(
                f"{cap.name} doesn't support output={req.output.value}; "
                f"supported: {[o.value for o in cap.supported_outputs]}"
            )

        # Validate early — before spawning subprocess (reviewer-flagged guard)
        if req.output == OutputMode.FILE and not req.output_path:
            raise ValueError(f"{cap.name}: FILE mode requires output_path")

        t0 = time.time()
        audio, sr = self._synthesize_raw(req)
        elapsed = time.time() - t0

        if req.target_sample_rate and req.target_sample_rate != sr:
            audio = _resample(audio, sr, req.target_sample_rate)
            sr = req.target_sample_rate

        audio = np.asarray(audio, dtype=np.float32).squeeze()
        dur = len(audio) / sr if sr else 0
        result = SynthesizeResult(
            duration_s=dur,
            sample_rate=sr,
            rtf=(elapsed / dur) if dur else float("inf"),
            engine=cap.name,
            output_mode=req.output,
        )

        if req.output == OutputMode.FILE:
            import soundfile as sf
            sf.write(req.output_path, audio, sr)
            result.audio_path = req.output_path
        elif req.output == OutputMode.BUFFER:
            import soundfile as sf
            buf = io.BytesIO()
            sf.write(buf, audio, sr, format="WAV")
            result.audio_bytes = buf.getvalue()
        elif req.output == OutputMode.BASE64:
            import soundfile as sf
            buf = io.BytesIO()
            sf.write(buf, audio, sr, format="WAV")
            result.audio_base64 = base64.b64encode(buf.getvalue()).decode()
        elif req.output == OutputMode.NUMPY:
            result.audio_numpy = audio
        elif req.output == OutputMode.TENSOR:
            import torch
            result.audio_tensor = torch.from_numpy(audio)
        elif req.output == OutputMode.STREAM:
            result.audio_stream = self._synthesize_stream(req)

        return result

    def _synthesize_stream(self, req: SynthesizeRequest) -> Iterator[bytes]:
        """Default: subclasses with native streaming override; otherwise raise."""
        raise NotImplementedError(f"{self.capability().name} has no streaming")

    @abstractmethod
    def healthcheck(self) -> dict: ...
