"""Audio capture operator — sounddevice callback → asyncio.Queue."""

from __future__ import annotations

import asyncio
import logging

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)


class AudioSource:
    """Captures microphone audio and feeds chunks to an asyncio queue.

    Each chunk is a float32 numpy array of shape (chunk_size,).
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_ms: int = 30,
        device: int | str | None = None,
    ):
        self.sample_rate = sample_rate
        self.chunk_size = int(sample_rate * chunk_ms / 1000)
        self.device = device
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
        chunk = indata[:, 0].copy()  # mono
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, chunk)
        except asyncio.QueueFull:
            pass  # drop oldest-ish — consumer too slow

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self.chunk_size,
            device=self.device,
            callback=self._callback,
        )
        self._stream.start()
        logger.info(
            "audio_source_started: rate=%d chunk=%d device=%s",
            self.sample_rate, self.chunk_size, self.device or "default",
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
