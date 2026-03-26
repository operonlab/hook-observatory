"""Remote Node SDK — HTTP client for the remote-node proxy station (port 10208).

The proxy station translates between local file paths and the Windows GPU
server's base64 protocol. This client talks to the proxy, not directly to
the Windows machine.

Usage:
    from workshop.clients.remote_node import RemoteNodeClient

    client = RemoteNodeClient()
    result = client.segment("/path/to/image.jpg", prompt="the cat")
    print(result["mask_path"])      # local path to saved mask

    result = client.caption("/path/to/photo.jpg", detail="detailed")
    print(result["caption"])

    if client.is_available():
        models = client.list_models()
"""

import os
from typing import Any

import httpx

from ._base import APIError

_MODULE = "remote-node"


class RemoteNodeError(APIError):
    """Raised on errors from the remote-node proxy station."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(status_code, detail, module=_MODULE)


class RemoteNodeClient:
    """HTTP client for the Remote Node proxy station (port 10208)."""

    def __init__(self, base_url: str | None = None, timeout: float = 130):
        from workshop.port_registry import get_url

        self.base_url = (
            base_url
            or os.environ.get("REMOTE_NODE_URL")
            or get_url("remote-node")
        ).rstrip("/")
        self._timeout = timeout
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(timeout=self._timeout)
        return self._client

    def close(self) -> None:
        if self._client and not self._client.is_closed:
            self._client.close()

    # ── Internal ──────────────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        json_body: dict | None = None,
        params: dict | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        url = f"{self.base_url}{path}"
        kwargs: dict[str, Any] = {"timeout": timeout or self._timeout}
        if json_body is not None:
            kwargs["json"] = json_body
        if params is not None:
            kwargs["params"] = {k: v for k, v in params.items() if v is not None}
        try:
            resp = self.client.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp
        except httpx.ConnectError:
            raise RemoteNodeError(
                0,
                f"Cannot connect to Remote Node proxy at {self.base_url}. "
                "Start: cd stations/remote-node && ~/.local/bin/python3 main.py",
            ) from None
        except httpx.TimeoutException:
            raise RemoteNodeError(
                504,
                f"Timeout ({self._timeout}s) waiting for Remote Node proxy at {self.base_url}",
            ) from None
        except httpx.HTTPStatusError as e:
            raise RemoteNodeError(
                e.response.status_code,
                e.response.text[:500],
            ) from e

    def _get(self, path: str, params: dict | None = None) -> Any:
        return self._request("GET", path, params=params).json()

    def _post(self, path: str, json_body: dict | None = None) -> Any:
        return self._request("POST", path, json_body=json_body).json()

    # ── Health ────────────────────────────────────────────────

    def health(self) -> dict:
        """Get composite health status (proxy + Windows connectivity)."""
        return self._get("/health")

    def is_available(self) -> bool:
        """Returns True if the proxy is running AND Windows node is reachable."""
        try:
            h = self.health()
            return h.get("remote_healthy", False)
        except Exception:
            return False

    # ── Segmentation ──────────────────────────────────────────

    def segment(
        self,
        file_path: str,
        prompt: str,
        task: str = "referring",
    ) -> dict:
        """Segment an image region based on text prompt.

        Returns:
            {"polygons": [...], "mask_path": str, "labels": [str]}
        """
        return self._post("/segment", {
            "file_path": file_path,
            "prompt": prompt,
            "task": task,
        })

    # ── Detection ─────────────────────────────────────────────

    def detect(self, file_path: str, prompt: str) -> dict:
        """Detect objects in image matching the text prompt.

        Returns:
            {"boxes": [...], "labels": [...], "scores": [...]}
        """
        return self._post("/detect", {
            "file_path": file_path,
            "prompt": prompt,
        })

    # ── Captioning ────────────────────────────────────────────

    def caption(self, file_path: str, detail: str = "brief") -> dict:
        """Generate a text caption for the image.

        Args:
            file_path: Absolute path to image file.
            detail: "brief" or "detailed".

        Returns:
            {"caption": str}
        """
        return self._post("/caption", {
            "file_path": file_path,
            "detail": detail,
        })

    # ── Batch Segmentation ────────────────────────────────────

    def batch_segment(self, file_path: str, prompts: list[str]) -> dict:
        """Segment multiple prompts on a single image.

        Returns:
            {"results": {prompt: {...}}, "composite_mask_path": str}
        """
        return self._post("/batch-segment", {
            "file_path": file_path,
            "prompts": prompts,
        })

    # ── Model Management ──────────────────────────────────────

    def list_models(self) -> dict:
        """List models available on the Windows GPU server."""
        return self._get("/models")

    def load_model(self, model: str) -> dict:
        """Load a model on the Windows GPU server."""
        return self._post("/models/load", {"model": model})

    def unload_model(self, model: str) -> dict:
        """Unload a model from the Windows GPU server."""
        return self._post("/models/unload", {"model": model})

    # ── Context Manager ───────────────────────────────────────

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __repr__(self) -> str:
        return f"RemoteNodeClient(base_url={self.base_url!r})"
