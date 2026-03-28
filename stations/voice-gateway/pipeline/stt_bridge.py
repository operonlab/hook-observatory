"""STT bridge — WebSocket client to STT station (:10200)."""

from __future__ import annotations

import json
import logging
from typing import Callable

import numpy as np
import websockets

logger = logging.getLogger(__name__)


class STTBridge:
    """Routes audio to the STT station via WebSocket.

    Follows the STT station's streaming protocol:
    1. Send JSON config
    2. Send raw PCM bytes (16-bit signed mono)
    3. Send {"type": "end"}
    4. Receive final result
    """

    def __init__(
        self,
        ws_url: str = "ws://127.0.0.1:10200/transcribe/stream",
        engine: str = "mlx-whisper",
        language: str = "zh-TW",
    ):
        self.ws_url = ws_url
        self.engine = engine
        self.language = language

    async def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
        on_partial: Callable[[str], None] | None = None,
    ) -> dict:
        """Send audio buffer to STT station and return transcription result.

        Args:
            audio: float32 numpy array (mono)
            sample_rate: audio sample rate
            on_partial: callback for partial results

        Returns:
            dict with keys: text, segments, engine, audio_duration_ms
        """
        # float32 → 16-bit signed PCM
        pcm_bytes = (audio * 32767).clip(-32768, 32767).astype(np.int16).tobytes()

        try:
            async with websockets.connect(self.ws_url, close_timeout=5) as ws:
                # Step 1: config handshake
                config = {
                    "engine": self.engine,
                    "language": self.language,
                    "sample_rate": sample_rate,
                    "buffer_ms": 1000,
                }
                await ws.send(json.dumps(config))
                ready = json.loads(await ws.recv())
                if ready.get("type") != "ready":
                    raise RuntimeError(f"STT handshake failed: {ready}")

                # Step 2: send PCM in 64KB chunks
                chunk_size = 64 * 1024
                for i in range(0, len(pcm_bytes), chunk_size):
                    await ws.send(pcm_bytes[i : i + chunk_size])

                # Step 3: signal end
                await ws.send(json.dumps({"type": "end"}))

                # Step 4: collect results
                result = {}
                while True:
                    msg = json.loads(await ws.recv())
                    if msg["type"] == "partial" and on_partial:
                        on_partial(msg.get("delta", ""))
                    elif msg["type"] == "final":
                        result = msg
                        break
                    elif msg["type"] == "error":
                        raise RuntimeError(f"STT error: {msg.get('error')}")

                logger.info(
                    "stt_result: text=%r engine=%s latency=%dms",
                    result.get("text", "")[:50],
                    result.get("engine"),
                    result.get("audio_duration_ms", 0),
                )
                return result

        except (ConnectionRefusedError, OSError) as e:
            logger.error("stt_connection_failed: %s", e)
            raise
