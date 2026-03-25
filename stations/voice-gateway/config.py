"""YAML config loader for Voice Gateway."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from workshop.station_bootstrap import load_yaml_config

_CONFIG_PATH = Path(__file__).parent / "config.yaml"


@dataclass
class ServerConfig:
    enabled: bool = True
    sample_rate: int = 16000
    chunk_ms: int = 30
    vad_model: str = "models/silero_vad.onnx"
    vad_threshold: float = 0.5
    kws_model_dir: str = "models/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"
    stt_ws_url: str = "ws://127.0.0.1:10200/transcribe/stream"
    stt_engine: str = "mlx-whisper"


@dataclass
class ClientConfig:
    whisper_model: str = "tiny"
    webgpu_preferred: bool = True


@dataclass
class Config:
    port: int = 10204
    host: str = "127.0.0.1"
    language: str = "zh-TW"
    keywords: list[str] = field(default_factory=lambda: ["你好助手", "嘿助手", "hey assistant"])
    sensitivity: float = 0.5
    server: ServerConfig = field(default_factory=ServerConfig)
    client: ClientConfig = field(default_factory=ClientConfig)
    redis_url: str = "redis://127.0.0.1:6379/0"
    stream_prefix: str = "ws:voice:"
    listening_timeout_s: float = 10.0
    processing_silence_s: float = 1.5
    processing_timeout_s: float = 30.0
    responding_timeout_s: float = 15.0
    min_speech_for_stt_s: float = 0.5


def load_config(path: Path | None = None) -> Config:
    raw = load_yaml_config(path or _CONFIG_PATH)
    cfg = Config()

    # Top-level scalars
    for key in (
        "port", "host", "language", "sensitivity",
        "redis_url", "stream_prefix",
        "listening_timeout_s", "processing_silence_s",
        "processing_timeout_s", "responding_timeout_s",
        "min_speech_for_stt_s",
    ):
        if key in raw:
            setattr(cfg, key, type(getattr(cfg, key))(raw[key]))

    if "keywords" in raw and isinstance(raw["keywords"], list):
        cfg.keywords = raw["keywords"]

    # Nested: server
    if "server" in raw and isinstance(raw["server"], dict):
        for key, val in raw["server"].items():
            if hasattr(cfg.server, key):
                expected = type(getattr(cfg.server, key))
                setattr(cfg.server, key, expected(val))

    # Nested: client
    if "client" in raw and isinstance(raw["client"], dict):
        for key, val in raw["client"].items():
            if hasattr(cfg.client, key):
                expected = type(getattr(cfg.client, key))
                setattr(cfg.client, key, expected(val))

    return cfg


config = load_config()
