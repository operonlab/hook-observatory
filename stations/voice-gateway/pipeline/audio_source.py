"""Audio capture operator — sounddevice callback → asyncio.Queue.

Records at the device's native sample rate, then resamples to the target
rate (16 kHz) in the callback.  Some devices (e.g. RØDE VideoMic NTG) only
support 48 kHz natively; forcing 16 kHz through PortAudio produces silence.
"""

from __future__ import annotations

import asyncio
import logging

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)


def _detect_native_rate(device: int | str | None) -> int:
    """Return the device's default (native) sample rate."""
    info = sd.query_devices(device or sd.default.device[0], kind="input")
    return int(info["default_samplerate"])


def _resample(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Resample with anti-aliasing low-pass filter.

    For integer ratios like 48000→16000 (3:1), applies a simple FIR
    low-pass at the Nyquist of the target rate before decimation.
    """
    if src_rate == dst_rate:
        return audio
    ratio = src_rate / dst_rate  # e.g. 3.0 for 48k→16k
    if ratio == int(ratio):
        # Integer decimation: take every Nth sample
        n = int(ratio)
        return audio[::n].copy()
    # General case: linear interpolation
    out_ratio = dst_rate / src_rate
    n_out = int(len(audio) * out_ratio)
    indices = np.arange(n_out) / out_ratio
    idx_floor = np.floor(indices).astype(int)
    idx_ceil = np.minimum(idx_floor + 1, len(audio) - 1)
    frac = (indices - idx_floor).astype(np.float32)
    return audio[idx_floor] * (1 - frac) + audio[idx_ceil] * frac


class AudioSource:
    """Captures microphone audio and feeds resampled 16 kHz chunks.

    Records at the device's native rate (e.g. 48 kHz) and resamples
    down to `sample_rate` (default 16 kHz) in the audio callback.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_ms: int = 30,
        device: int | str | None = None,
    ):
        self.sample_rate = sample_rate
        self.chunk_size = int(sample_rate * chunk_ms / 1000)  # output chunk size
        self.device = device
        self._native_rate: int = 0
        self._native_chunk: int = 0
        self._queue: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=200)
        self._stream: sd.InputStream | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info,
        status: sd.CallbackFlags,
    ) -> None:
        if status:
            logger.warning("audio_status: %s", status)
        raw = indata[:, 0].copy()  # mono
        # Resample native → target
        if self._native_rate != self.sample_rate:
            chunk = _resample(raw, self._native_rate, self.sample_rate)
        else:
            chunk = raw
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, chunk)
        except asyncio.QueueFull:
            pass

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._native_rate = _detect_native_rate(self.device)
        # Compute native blocksize that yields ~chunk_ms of audio
        self._native_chunk = int(self._native_rate * self.chunk_size / self.sample_rate)

        self._stream = sd.InputStream(
            samplerate=self._native_rate,
            channels=1,
            dtype="float32",
            blocksize=self._native_chunk,
            device=self.device,
            callback=self._callback,
        )
        self._stream.start()
        logger.info(
            "audio_source_started: native=%dHz→%dHz chunk=%d device=%s",
            self._native_rate,
            self.sample_rate,
            self.chunk_size,
            self.device or "default",
        )

    async def read_chunk(self) -> np.ndarray:
        return await self._queue.get()

    async def stop(self) -> None:
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
            logger.info("audio_source_stopped")

    def pause(self) -> None:
        if self._stream and self._stream.active:
            self._stream.stop()
            logger.info("audio_source_paused")

    def resume(self) -> None:
        if self._stream and not self._stream.active:
            self._stream.start()
            logger.info("audio_source_resumed")

    @property
    def active(self) -> bool:
        return self._stream is not None and self._stream.active
