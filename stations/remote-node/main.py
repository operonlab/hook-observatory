"""Remote Node Proxy Station — forwards requests to Windows GPU server.

Translates between local Workshop conventions (file paths on Mac) and
the Windows GPU server conventions (base64-encoded payloads over HTTP).

The proxy reads local files, base64-encodes them, forwards to the remote
node over Tailscale, decodes results, saves output files locally, and
returns Workshop-friendly local paths.

Usage:
    cd stations/remote-node && ~/.local/bin/python3 main.py
    # or via workshop_services.py
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("remote-node")

# ── Config ────────────────────────────────────────────────────

_CONFIG_PATH = Path(__file__).parent / "config.yaml"


def _load_config() -> dict:
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}
    return {}


_cfg = _load_config()
PORT = int(_cfg.get("port", 10208))
HOST = _cfg.get("host", "127.0.0.1")
REMOTE_URL = _cfg.get("remote_url", "http://win-gpu:7860").rstrip("/")
HEALTH_INTERVAL = int(_cfg.get("health_interval", 30))
TIMEOUT = int(_cfg.get("timeout", 120))
OUTPUT_DIR = Path(os.path.expanduser(_cfg.get("output_dir", "~/workshop/outputs/remote-node")))

# ── State ─────────────────────────────────────────────────────

_remote_healthy: bool = False
_remote_last_check: float = 0.0
_remote_last_error: str = ""
_health_task: asyncio.Task | None = None


# ── Schemas ───────────────────────────────────────────────────


class SegmentRequest(BaseModel):
    file_path: str
    prompt: str
    task: str = Field(default="referring", description="Segmentation task type")


class DetectRequest(BaseModel):
    file_path: str
    prompt: str


class CaptionRequest(BaseModel):
    file_path: str
    prompt: str = Field(default="", description="Optional caption prompt (e.g. 'Describe this image in detail')")
    detail: str = Field(default="brief", pattern="^(brief|detailed)$")


class BatchSegmentRequest(BaseModel):
    file_path: str
    prompts: list[str]


class ModelRequest(BaseModel):
    model: str


# ── Helpers ───────────────────────────────────────────────────


def _ensure_output_dir() -> Path:
    """Create output directory if it doesn't exist."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


def _read_file_b64(file_path: str) -> str:
    """Read a local file and return base64-encoded content."""
    resolved = Path(os.path.expanduser(file_path)).resolve()
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")
    return base64.b64encode(resolved.read_bytes()).decode("ascii")


def _save_b64_file(b64_data: str, filename: str) -> str:
    """Decode base64 data and save to output dir. Returns local path."""
    out_dir = _ensure_output_dir()
    out_path = out_dir / filename
    out_path.write_bytes(base64.b64decode(b64_data))
    return str(out_path)


def _assert_remote_healthy():
    """Raise 503 if remote node is unreachable."""
    if not _remote_healthy:
        detail = "Windows GPU server is unreachable."
        if _remote_last_error:
            detail += f" Last error: {_remote_last_error}"
        detail += f" Remote URL: {REMOTE_URL}"
        raise HTTPException(status_code=503, detail=detail)


def _make_output_filename(prefix: str, ext: str = ".png") -> str:
    """Generate a timestamped output filename."""
    ts = int(time.time() * 1000)
    return f"{prefix}_{ts}{ext}"


async def _forward_json(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    json_body: dict | None = None,
) -> dict:
    """Forward a request to the remote node and return parsed JSON."""
    url = f"{REMOTE_URL}{path}"
    try:
        resp = await client.request(method, url, json=json_body, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot connect to Windows GPU server at {REMOTE_URL}",
        ) from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail=f"Timeout ({TIMEOUT}s) waiting for Windows GPU server",
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Remote error: {exc.response.text[:500]}",
        ) from exc


# ── Background Health Check ──────────────────────────────────


async def _health_checker():
    """Ping remote node periodically to track connectivity."""
    global _remote_healthy, _remote_last_check, _remote_last_error
    async with httpx.AsyncClient() as client:
        while True:
            try:
                resp = await client.get(
                    f"{REMOTE_URL}/health", timeout=10
                )
                resp.raise_for_status()
                _remote_healthy = True
                _remote_last_error = ""
            except Exception as exc:
                _remote_healthy = False
                _remote_last_error = str(exc)
                logger.warning("Remote node health check failed: %s", exc)
            _remote_last_check = time.time()
            await asyncio.sleep(HEALTH_INTERVAL)


# ── Lifespan ──────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _health_task
    _ensure_output_dir()
    _health_task = asyncio.create_task(_health_checker())
    logger.info("Remote Node proxy started → %s", REMOTE_URL)
    yield
    if _health_task:
        _health_task.cancel()


app = FastAPI(
    title="Remote Node Proxy",
    version="0.1.0",
    description="Proxy station forwarding requests to Windows GPU server over Tailscale",
    lifespan=lifespan,
)


# ── Endpoints ─────────────────────────────────────────────────


@app.get("/health")
async def health():
    """Composite health: proxy status + remote node connectivity."""
    return JSONResponse(content={
        "status": "ok",
        "service": "remote-node",
        "port": PORT,
        "remote_url": REMOTE_URL,
        "remote_healthy": _remote_healthy,
        "remote_last_check": _remote_last_check,
        "remote_last_error": _remote_last_error or None,
    })


@app.post("/segment")
async def segment(req: SegmentRequest):
    """Segment image: read local file, b64 encode, forward, save mask result."""
    _assert_remote_healthy()

    image_b64 = _read_file_b64(req.file_path)
    # Windows API uses "image" + "text" (not "prompt")
    payload = {
        "image": image_b64,
        "text": req.prompt,
    }

    async with httpx.AsyncClient() as client:
        result = await _forward_json(client, "POST", "/segment", payload)

    # Windows returns "mask_base64"; decode and save locally
    mask_path = None
    if result.get("mask_base64"):
        filename = _make_output_filename("mask")
        mask_path = _save_b64_file(result["mask_base64"], filename)
        result["mask_path"] = mask_path
        del result["mask_base64"]  # Don't return raw b64 to caller

    return JSONResponse(content=result)


@app.post("/detect")
async def detect(req: DetectRequest):
    """Detect objects: forward to Windows, return bounding boxes."""
    _assert_remote_healthy()

    image_b64 = _read_file_b64(req.file_path)
    # Windows API uses "image" + "text" (not "prompt")
    payload = {
        "image": image_b64,
        "text": req.prompt,
    }

    async with httpx.AsyncClient() as client:
        result = await _forward_json(client, "POST", "/detect", payload)

    return JSONResponse(content=result)


@app.post("/caption")
async def caption(req: CaptionRequest):
    """Caption image: forward to Windows, return text description."""
    _assert_remote_healthy()

    image_b64 = _read_file_b64(req.file_path)
    # Windows API uses "image" + "text"; map detail level into the text prompt
    text = req.prompt if req.prompt else (
        "Describe this image in detail." if req.detail == "detailed"
        else "What is in this image?"
    )
    payload = {
        "image": image_b64,
        "text": text,
    }

    async with httpx.AsyncClient() as client:
        result = await _forward_json(client, "POST", "/caption", payload)

    return JSONResponse(content=result)


@app.post("/batch-segment")
async def batch_segment(req: BatchSegmentRequest):
    """Batch segment: multiple prompts on one image, save all masks."""
    _assert_remote_healthy()

    image_b64 = _read_file_b64(req.file_path)
    # Windows API uses "image" + "prompts"
    payload = {
        "image": image_b64,
        "prompts": req.prompts,
    }

    async with httpx.AsyncClient() as client:
        result = await _forward_json(client, "POST", "/batch-segment", payload)

    # Save individual masks (Windows returns "mask_base64" per result)
    results = result.get("results", {})
    for prompt_key, seg_data in results.items():
        if seg_data.get("mask_base64"):
            safe_key = prompt_key.replace(" ", "_")[:30]
            filename = _make_output_filename(f"mask_{safe_key}")
            seg_data["mask_path"] = _save_b64_file(seg_data["mask_base64"], filename)
            del seg_data["mask_base64"]

    # Save composite mask if present
    composite_path = None
    if result.get("composite_mask_base64"):
        filename = _make_output_filename("composite")
        composite_path = _save_b64_file(result["composite_mask_base64"], filename)
        result["composite_mask_path"] = composite_path
        del result["composite_mask_base64"]

    return JSONResponse(content=result)


@app.get("/models")
async def list_models():
    """List available models on the Windows GPU server."""
    _assert_remote_healthy()

    async with httpx.AsyncClient() as client:
        return await _forward_json(client, "GET", "/models")


@app.post("/models/load")
async def load_model(req: ModelRequest):
    """Load a model on the Windows GPU server."""
    _assert_remote_healthy()

    async with httpx.AsyncClient() as client:
        return await _forward_json(client, "POST", "/models/load", {"model": req.model})


@app.post("/models/unload")
async def unload_model(req: ModelRequest):
    """Unload a model on the Windows GPU server."""
    _assert_remote_healthy()

    async with httpx.AsyncClient() as client:
        return await _forward_json(
            client, "POST", "/models/unload", {"model": req.model}
        )


# ── Main ──────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    uvicorn.run(app, host=HOST, port=PORT)
