"""Object detection operator -- calls vision station HTTP API.

Supports YOLO (default), Claude, Gemini engines via the running
vision station at port 10203.

Usage:
    from image_ops.detect import DetectOp
    op = DetectOp(engine="yolo")
    ctx = op({"image_path": "/path/to/image.jpg"})
    # ctx["detections"] -> [{"label": "person", "confidence": 0.95, "bbox": [x1,y1,x2,y2]}]
"""

from __future__ import annotations

import logging
from typing import Any

from . import register

logger = logging.getLogger(__name__)


@register("detect")
class DetectOp:
    """Object detection via vision station HTTP API."""

    name = "detect"
    input_keys = ("image_path",)
    output_keys = ("detections",)

    def __init__(
        self,
        engine: str = "yolo",
        task: str = "detect",
        station_url: str = "http://127.0.0.1:10203",
        timeout: float = 30.0,
    ):
        self._engine = engine
        self._task = task
        self._station_url = station_url.rstrip("/")
        self._timeout = timeout

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        import httpx

        image_path = ctx["image_path"]
        url = f"{self._station_url}/analyze"
        params = {
            "path": image_path,
            "engine": self._engine,
            "task": self._task,
        }

        try:
            resp = httpx.post(url, params=params, timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
        except httpx.ConnectError:
            logger.warning(
                "DetectOp: vision station unreachable at %s",
                self._station_url,
            )
            ctx["detections"] = []
            return ctx
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "DetectOp: vision station returned %d: %s",
                exc.response.status_code,
                exc.response.text[:200],
            )
            ctx["detections"] = []
            return ctx
        except httpx.TimeoutException:
            logger.warning(
                "DetectOp: request timed out after %.1fs",
                self._timeout,
            )
            ctx["detections"] = []
            return ctx

        # Normalize vision station response to standard format.
        # Station returns: {"class": str, "confidence": float,
        #   "bbox": {"x1": float, "y1": float, "x2": float, "y2": float}}
        # We normalize to: {"label": str, "confidence": float, "bbox": [x1, y1, x2, y2]}
        raw_detections = data.get("result", [])
        detections = []
        for det in raw_detections:
            bbox_raw = det.get("bbox", {})
            if isinstance(bbox_raw, dict):
                bbox = [
                    bbox_raw.get("x1", 0),
                    bbox_raw.get("y1", 0),
                    bbox_raw.get("x2", 0),
                    bbox_raw.get("y2", 0),
                ]
            elif isinstance(bbox_raw, list):
                bbox = bbox_raw
            else:
                bbox = [0, 0, 0, 0]

            detections.append(
                {
                    "label": det.get("class", det.get("label", "unknown")),
                    "confidence": det.get("confidence", 0.0),
                    "bbox": bbox,
                }
            )

        ctx["detections"] = detections
        logger.info(
            "DetectOp: engine=%s, found %d objects in %s",
            self._engine,
            len(detections),
            image_path,
        )
        return ctx
