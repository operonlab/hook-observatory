"""oMLX embedding bridge — persistent subprocess for MLX-native embeddings.

Manages a long-running mlx-embeddings worker process (Qwen3-Embedding-0.6B, 1024d).
The worker loads the model once and serves requests via stdin/stdout JSON lines.
Falls back gracefully: returns None when worker is unavailable.
"""

import asyncio
import json
import logging
import subprocess
from pathlib import Path

try:
    from workshop.retry import async_with_backoff as _async_with_backoff
    from workshop.timeout import dynamic_timeout as _dynamic_timeout
    _HAS_RETRY = True
except ImportError:
    _HAS_RETRY = False

logger = logging.getLogger(__name__)

OMLX_VENV = Path.home() / ".venvs" / "omlx"
WORKER_SCRIPT = OMLX_VENV / "embed_worker.py"
PYTHON = OMLX_VENV / "bin" / "python3"
EMBEDDING_DIM: int = 1024  # re-declared; canonical value in search_constants.py

_process: subprocess.Popen | None = None
_startup_lock = asyncio.Lock()  # protects worker process startup
_io_lock = asyncio.Lock()       # protects stdin/stdout I/O atomicity
_ready = False


async def _ensure_worker() -> bool:
    """Start the worker process if not running."""
    global _process, _ready

    async with _startup_lock:
        if _process is not None and _process.poll() is None and _ready:
            return True

        if not PYTHON.exists() or not WORKER_SCRIPT.exists():
            logger.warning("oMLX venv or worker not found at %s", OMLX_VENV)
            return False

        try:
            _process = subprocess.Popen(  # noqa: ASYNC220, S603
                [str(PYTHON), str(WORKER_SCRIPT)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            loop = asyncio.get_event_loop()
            line = await loop.run_in_executor(None, _process.stdout.readline)
            if not line:
                logger.warning("oMLX worker produced no output")
                _process.kill()
                _process = None
                return False

            status = json.loads(line.strip())
            if status.get("status") == "ready":
                _ready = True
                logger.info("oMLX embedding worker ready: %s", status.get("model"))
                return True

            logger.warning("oMLX worker unexpected status: %s", status)
            _process.kill()
            _process = None
            return False
        except Exception as e:
            logger.warning("Failed to start oMLX worker: %s", e)
            if _process:
                try:
                    _process.kill()
                except ProcessLookupError:
                    pass
            _process = None
            _ready = False
            return False


async def _send_request(request: dict) -> dict | None:
    """Send a JSON request to worker and read response."""
    global _process, _ready

    if not await _ensure_worker():
        return None

    async with _io_lock:
        try:
            line = json.dumps(request) + "\n"
            loop = asyncio.get_event_loop()

            def _write_request() -> None:
                _process.stdin.write(line)
                _process.stdin.flush()

            write_timeout = _dynamic_timeout(base=10, factor=0.5, context=len(line), cap=30) if _HAS_RETRY else 10
            await asyncio.wait_for(
                loop.run_in_executor(None, _write_request),
                timeout=write_timeout,
            )

            read_timeout = _dynamic_timeout(base=30, factor=0.5, context=len(line), cap=120) if _HAS_RETRY else 30
            response_line = await asyncio.wait_for(
                loop.run_in_executor(None, _process.stdout.readline),
                timeout=read_timeout,
            )
            if not response_line:
                logger.warning("oMLX worker returned empty response")
                _ready = False
                return None

            return json.loads(response_line.strip())
        except Exception as e:
            logger.warning("oMLX bridge error: %s", e)
            _ready = False
            if _process:
                try:
                    _process.kill()
                except ProcessLookupError:
                    pass
            _process = None
            return None


async def _embed_texts_once(texts: list[str], task_type: str | None) -> list[list[float] | None]:
    """Single attempt to embed texts via worker (no retry)."""
    response = await _send_request({"texts": texts, "task_type": task_type})

    if response is None or "error" in response:
        if response:
            logger.warning("oMLX embedding error: %s", response.get("error"))
        return [None] * len(texts)

    embeddings = response.get("embeddings", [])
    results: list[list[float] | None] = []
    for i in range(len(texts)):
        if i < len(embeddings) and embeddings[i] and len(embeddings[i]) == EMBEDDING_DIM:
            results.append(embeddings[i])
        else:
            results.append(None)
    return results


async def embed_texts(texts: list[str], task_type: str | None = None) -> list[list[float] | None]:
    """Embed multiple texts. Returns list of embeddings (or None per failed text).

    Retries up to 2 times on Exception (worker crash triggers restart via _send_request).
    """
    if not texts:
        return []

    if _HAS_RETRY:
        try:
            return await _async_with_backoff(
                max_retries=2,
                base_delay=1.0,
                max_delay=10.0,
            )(_embed_texts_once)(texts, task_type)
        except Exception as exc:
            logger.warning("oMLX embed_texts failed after retries: %s", exc)
            return [None] * len(texts)
    else:
        return await _embed_texts_once(texts, task_type)


async def embed_single(text: str, task_type: str | None = None) -> list[float] | None:
    """Embed a single text."""
    results = await embed_texts([text], task_type=task_type)
    return results[0] if results else None


async def shutdown():
    """Gracefully shutdown the worker process."""
    global _process, _ready
    if _process and _process.poll() is None:
        try:
            _process.stdin.close()
            _process.wait(timeout=5)
        except Exception:
            _process.kill()
    _process = None
    _ready = False
