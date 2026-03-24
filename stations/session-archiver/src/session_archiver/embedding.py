"""Embedding service — oMLX bridge for session-archiver (sync CLI tool).

Uses the same oMLX worker pattern as core/src/shared/omlx_bridge.py
but in synchronous mode for CLI usage.
Graceful degradation: returns None when oMLX worker is unavailable.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


class SyncOmlxWorker:
    """Synchronous oMLX embedding worker for CLI tools."""

    def __init__(self, venv_path: str, dim: int = 1024):
        self.venv = Path(venv_path)
        self.python = self.venv / "bin" / "python3"
        self.worker_script = self.venv / "embed_worker.py"
        self.dim = dim
        self.proc = None

    def _ensure_worker(self) -> bool:
        if self.proc is not None and self.proc.poll() is None:
            return True

        if not self.python.exists() or not self.worker_script.exists():
            logger.warning("omlx_venv_missing", path=str(self.venv))
            return False

        try:
            self.proc = subprocess.Popen(  # noqa: S603
                [str(self.python), str(self.worker_script)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            line = self.proc.stdout.readline()
            if not line:
                logger.warning("omlx_worker_no_output")
                self.proc.kill()
                self.proc = None
                return False
            status = json.loads(line.strip())
            if status.get("status") == "ready":
                logger.info("omlx_worker_ready", model=status.get("model"))
                return True
            logger.warning("omlx_worker_bad_status", status=status)
            self.proc.kill()
            self.proc = None
            return False
        except Exception as e:
            logger.warning("omlx_worker_start_failed", error=str(e))
            if self.proc:
                try:
                    self.proc.kill()
                except ProcessLookupError:
                    pass
            self.proc = None
            return False

    def shutdown(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()
        self.proc = None


_worker: SyncOmlxWorker | None = None


def _get_worker(venv_path: str, dim: int) -> SyncOmlxWorker | None:
    global _worker
    if _worker is None:
        _worker = SyncOmlxWorker(venv_path, dim)
    if _worker._ensure_worker():
        return _worker
    return None


def get_embedding(
    text: str, omlx_venv: str = str(Path.home() / ".venvs" / "omlx"), dim: int = 1024
) -> list[float] | None:
    """Generate embedding vector for text via oMLX worker."""
    worker = _get_worker(omlx_venv, dim)
    if worker is None:
        return None

    try:
        request = json.dumps({"texts": [text], "task_type": "search_document"}) + "\n"
        worker.proc.stdin.write(request)
        worker.proc.stdin.flush()
        line = worker.proc.stdout.readline()
        if not line:
            logger.warning("omlx_empty_response")
            return None
        response = json.loads(line.strip())
        if "error" in response:
            logger.warning("omlx_error", error=response["error"])
            return None
        embeddings = response.get("embeddings", [])
        if embeddings and embeddings[0] and len(embeddings[0]) == dim:
            return embeddings[0]
        logger.warning(
            "unexpected_embedding_dim",
            expected=dim,
            actual=len(embeddings[0]) if embeddings and embeddings[0] else 0,
        )
        return None
    except Exception as e:
        logger.warning("embedding_failed", error=str(e))
        return None


def get_embeddings_batch(
    texts: list[str], omlx_venv: str = str(Path.home() / ".venvs" / "omlx"), dim: int = 1024
) -> list[list[float] | None]:
    """Generate embeddings for multiple texts in a single call."""
    worker = _get_worker(omlx_venv, dim)
    if worker is None:
        return [None] * len(texts)

    try:
        request = json.dumps({"texts": texts, "task_type": "search_document"}) + "\n"
        worker.proc.stdin.write(request)
        worker.proc.stdin.flush()
        line = worker.proc.stdout.readline()
        if not line:
            return [None] * len(texts)
        response = json.loads(line.strip())
        if "error" in response:
            return [None] * len(texts)
        embeddings = response.get("embeddings", [])
        results: list[list[float] | None] = []
        for i in range(len(texts)):
            if i < len(embeddings) and embeddings[i] and len(embeddings[i]) == dim:
                results.append(embeddings[i])
            else:
                results.append(None)
        return results
    except Exception as e:
        logger.warning("batch_embedding_failed", error=str(e))
        return [None] * len(texts)
