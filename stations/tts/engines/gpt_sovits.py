"""GPT-SoVITS engine — zero-shot voice cloning TTS via HTTP bridge.

Manages the GPT-SoVITS api_v2.py server as a subprocess and communicates
via HTTP. The server is started lazily on first request and auto-stopped
after MODEL_IDLE_TTL seconds of inactivity.

Requires:
  - GPT-SoVITS cloned at ~/workshop/lab/gpt-sovits/
  - Pretrained models downloaded (see GPT_SoVITS/download.py)
  - A Python env with GPT-SoVITS deps (can use its own venv)
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from . import register

logger = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────
GPT_SOVITS_ROOT = Path.home() / "workshop" / "lab" / "gpt-sovits"
API_SCRIPT = GPT_SOVITS_ROOT / "api_v2.py"
CONFIG_PATH = GPT_SOVITS_ROOT / "GPT_SoVITS" / "configs" / "tts_infer.yaml"
ALFRED_REF = "/Users/joneshong/workshop/lab/rvc-mlx/datasets/alfred/clean_final/real_01_clean.wav"

# ── Server config ──────────────────────────────────────────────────────────
_SERVER_HOST = "127.0.0.1"
_SERVER_PORT = 9880
_BASE_URL = f"http://{_SERVER_HOST}:{_SERVER_PORT}"
_STARTUP_TIMEOUT = 120  # seconds to wait for server readiness
_HEALTH_POLL_INTERVAL = 2  # seconds between readiness checks

# ── Idle management ───────────────────────────────────────────────────────
_last_used: float = 0.0
MODEL_IDLE_TTL = 600  # 10 min — longer because subprocess startup is expensive
_server_proc: subprocess.Popen | None = None

# Voice ID -> (ref_audio_path, prompt_text, prompt_lang)
_VOICE_MAP: dict[str, dict] = {
    "default": {
        "ref_audio_path": ALFRED_REF,
        "prompt_text": "",
        "prompt_lang": "zh",
    },
    "alfred": {
        "ref_audio_path": ALFRED_REF,
        "prompt_text": "",
        "prompt_lang": "zh",
    },
}


def _mark_used():
    global _last_used
    _last_used = time.monotonic()


def _is_server_running() -> bool:
    """Check if the GPT-SoVITS API server is reachable."""
    try:
        req = Request(
            f"{_BASE_URL}/tts?text=ping&text_lang=en&ref_audio_path=x&prompt_lang=en", method="GET"
        )
        # We just check connectivity, not a valid TTS call
        urlopen(req, timeout=3)
        return True
    except Exception:
        # Try a simpler check — see if the port is open
        import socket

        try:
            with socket.create_connection((_SERVER_HOST, _SERVER_PORT), timeout=2):
                return True
        except (OSError, ConnectionRefusedError):
            return False


def _start_server():
    """Start the GPT-SoVITS api_v2.py server as a subprocess."""
    global _server_proc

    if _server_proc is not None and _server_proc.poll() is None:
        if _is_server_running():
            return
        # Process exists but port not responding — kill and restart
        logger.warning("GPT-SoVITS process alive but not responding, restarting...")
        _stop_server()

    if not API_SCRIPT.exists():
        raise FileNotFoundError(
            f"GPT-SoVITS not found at {GPT_SOVITS_ROOT}. "
            "Clone it: git clone https://github.com/RVC-Boss/GPT-SoVITS.git ~/workshop/lab/gpt-sovits"
        )

    # Determine Python interpreter — prefer GPT-SoVITS's own venv if it exists
    venv_python = GPT_SOVITS_ROOT / ".venv" / "bin" / "python3"
    if venv_python.exists():
        python_bin = str(venv_python)
    else:
        # Fall back to system python (user must have deps installed)
        python_bin = str(Path.home() / ".local" / "bin" / "python3")

    cmd = [
        python_bin,
        str(API_SCRIPT),
        "-a",
        _SERVER_HOST,
        "-p",
        str(_SERVER_PORT),
        "-c",
        str(CONFIG_PATH),
    ]

    logger.info("Starting GPT-SoVITS API server: %s", " ".join(cmd))

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{GPT_SOVITS_ROOT}:{GPT_SOVITS_ROOT / 'GPT_SoVITS'}"

    _server_proc = subprocess.Popen(
        cmd,
        cwd=str(GPT_SOVITS_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        # Ensure the subprocess gets its own process group so we can kill it cleanly
        preexec_fn=os.setsid,
    )

    # Wait for server to become ready
    start = time.monotonic()
    while time.monotonic() - start < _STARTUP_TIMEOUT:
        if _server_proc.poll() is not None:
            # Process exited prematurely
            stderr = (
                _server_proc.stderr.read().decode(errors="replace") if _server_proc.stderr else ""
            )
            raise RuntimeError(
                f"GPT-SoVITS server exited with code {_server_proc.returncode}. "
                f"stderr: {stderr[:500]}"
            )
        if _is_server_running():
            logger.info(
                "GPT-SoVITS API server ready on port %d (took %.1fs)",
                _SERVER_PORT,
                time.monotonic() - start,
            )
            return
        time.sleep(_HEALTH_POLL_INTERVAL)

    # Timeout — kill the process
    _stop_server()
    raise TimeoutError(
        f"GPT-SoVITS server failed to start within {_STARTUP_TIMEOUT}s. "
        "Check if pretrained models are downloaded."
    )


def _stop_server():
    """Stop the GPT-SoVITS API server subprocess."""
    global _server_proc
    if _server_proc is None:
        return
    try:
        # Kill the entire process group
        os.killpg(os.getpgid(_server_proc.pid), signal.SIGTERM)
        _server_proc.wait(timeout=10)
    except (ProcessLookupError, OSError):
        pass
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(_server_proc.pid), signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass
    _server_proc = None
    logger.info("GPT-SoVITS API server stopped")


def unload_model() -> bool:
    """Stop the GPT-SoVITS server and free resources. Returns True if stopped."""
    if _server_proc is None:
        return False
    _stop_server()
    return True


def is_idle() -> bool:
    """Check if server is running but idle beyond TTL."""
    if _server_proc is None:
        return False
    return (time.monotonic() - _last_used) > MODEL_IDLE_TTL


def _detect_language(text: str) -> str:
    """Simple language detection based on Unicode ranges."""
    for ch in text:
        cp = ord(ch)
        # CJK Unified Ideographs
        if 0x4E00 <= cp <= 0x9FFF:
            return "zh"
        # Hiragana or Katakana
        if 0x3040 <= cp <= 0x30FF:
            return "ja"
        # Hangul
        if 0xAC00 <= cp <= 0xD7AF:
            return "ko"
    return "en"


def _call_tts_api(
    text: str,
    ref_audio_path: str,
    text_lang: str = "zh",
    prompt_text: str = "",
    prompt_lang: str = "zh",
    speed: float = 1.0,
) -> bytes:
    """Call the GPT-SoVITS /tts endpoint and return WAV bytes."""
    import json as _json

    payload = {
        "text": text,
        "text_lang": text_lang,
        "ref_audio_path": ref_audio_path,
        "prompt_text": prompt_text,
        "prompt_lang": prompt_lang,
        "text_split_method": "cut5",
        "batch_size": 1,
        "speed_factor": speed,
        "media_type": "wav",
        "streaming_mode": False,
    }

    data = _json.dumps(payload).encode("utf-8")
    req = Request(
        f"{_BASE_URL}/tts",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        resp = urlopen(req, timeout=120)
        if resp.status != 200:
            body = resp.read().decode(errors="replace")
            raise RuntimeError(f"GPT-SoVITS API returned {resp.status}: {body[:300]}")
        return resp.read()
    except URLError as e:
        raise RuntimeError(f"GPT-SoVITS API request failed: {e}") from e


@register("gpt-sovits")
class GPTSoVITSEngine:
    """GPT-SoVITS — zero-shot voice cloning TTS via HTTP bridge to api_v2.py."""

    name = "gpt-sovits"

    def synthesize(
        self,
        text: str,
        voice: str = "default",
        speed: float = 1.0,
        output_path: str | None = None,
    ) -> dict:
        # Verify GPT-SoVITS is cloned
        if not API_SCRIPT.exists():
            return {
                "error": (
                    "GPT-SoVITS not found. Clone it:\n"
                    "  git clone https://github.com/RVC-Boss/GPT-SoVITS.git "
                    "~/workshop/lab/gpt-sovits"
                ),
                "engine": "gpt-sovits",
            }

        _mark_used()

        # Start server if not running
        try:
            _start_server()
        except Exception as e:
            logger.exception("Failed to start GPT-SoVITS server")
            return {"error": f"GPT-SoVITS server startup failed: {e}", "engine": "gpt-sovits"}

        try:
            out_path = output_path or tempfile.mktemp(suffix=".wav", prefix="tts_gptsovits_")

            # Resolve voice config
            voice_cfg = _VOICE_MAP.get(voice)
            if voice_cfg is None:
                if voice.startswith("/") and os.path.isfile(voice):
                    # Treat as direct path to reference audio
                    voice_cfg = {"ref_audio_path": voice, "prompt_text": "", "prompt_lang": "zh"}
                else:
                    logger.warning("Unknown voice '%s', falling back to default", voice)
                    voice_cfg = _VOICE_MAP["default"]

            # Convert Traditional → Simplified Chinese for better pronunciation
            from . import to_simplified

            text = to_simplified(text)

            # Auto-detect text language
            text_lang = _detect_language(text)

            wav_bytes = _call_tts_api(
                text=text,
                ref_audio_path=voice_cfg["ref_audio_path"],
                text_lang=text_lang,
                prompt_text=voice_cfg.get("prompt_text", ""),
                prompt_lang=voice_cfg.get("prompt_lang", "zh"),
                speed=speed,
            )

            with open(out_path, "wb") as f:
                f.write(wav_bytes)

            # Calculate duration from WAV
            duration = 0.0
            sample_rate = 32000
            try:
                import wave

                with wave.open(out_path, "rb") as w:
                    sample_rate = w.getframerate()
                    duration = w.getnframes() / sample_rate
            except Exception:
                # Fallback: estimate from file size (16-bit mono WAV)
                file_size = os.path.getsize(out_path)
                duration = max(0, (file_size - 44)) / (sample_rate * 2)

            return {
                "audio_path": out_path,
                "duration": round(duration, 3),
                "sample_rate": sample_rate,
                "engine": "gpt-sovits",
            }
        except Exception as e:
            logger.exception("GPT-SoVITS synthesis failed")
            return {"error": f"GPT-SoVITS failed: {e}", "engine": "gpt-sovits"}

    def list_voices(self) -> list[dict]:
        return [
            {"id": "default", "name": "Default (Alfred)", "language": "zh"},
            {"id": "alfred", "name": "Alfred Pennyworth", "language": "zh"},
        ]
