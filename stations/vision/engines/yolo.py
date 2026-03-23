"""YOLO engine — real-time object detection via CoreML.

Uses ultralytics YOLO11n for 80-class COCO detection at 85+ FPS.
CoreML format uses Neural Engine for maximum efficiency on Apple Silicon.

Requires: pip install ultralytics
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from . import register

logger = logging.getLogger(__name__)

_last_used: float = 0.0
MODEL_IDLE_TTL = 300
_model = None


def _mark_used():
    global _last_used
    _last_used = time.monotonic()


def unload_model() -> bool:
    """Unload YOLO model and free memory. Returns True if unloaded."""
    import gc

    global _model
    if _model is None:
        return False
    _model = None
    gc.collect()
    logger.info("Unloaded YOLO model, memory freed")
    return True


def is_idle() -> bool:
    """Check if model is loaded but idle beyond TTL."""
    if _model is None:
        return False
    return (time.monotonic() - _last_used) > MODEL_IDLE_TTL


def _load():
    global _model
    if _model is not None:
        return
    from ultralytics import YOLO

    logger.info("Loading YOLO model...")
    _model = YOLO("yolo11n.pt")
    logger.info("YOLO model loaded")


@register("yolo")
class YOLOEngine:
    """YOLO11 — real-time object detection, 80 COCO classes."""

    name = "yolo"

    def analyze(self, file_path: str, task: str = "detect", prompt: str | None = None) -> dict:
        if task != "detect":
            return {
                "error": f"YOLO engine only supports task='detect', got '{task}'",
                "engine": "yolo",
                "task": task,
            }

        path = Path(file_path)
        if not path.exists():
            return {"error": f"File not found: {file_path}", "engine": "yolo", "task": task}

        try:
            from ultralytics import YOLO  # noqa: F401
        except ImportError:
            return {
                "error": "ultralytics not installed. Run: pip install ultralytics",
                "engine": "yolo",
                "task": task,
            }

        _mark_used()
        _load()

        try:
            results = _model(str(path), verbose=False)
            detections = []

            for r in results:
                for box in r.boxes:
                    cls_id = int(box.cls[0])
                    conf = float(box.conf[0])
                    x1, y1, x2, y2 = box.xyxy[0].tolist()

                    detections.append(
                        {
                            "class": r.names[cls_id],
                            "class_id": cls_id,
                            "confidence": round(conf, 4),
                            "bbox": {
                                "x1": round(x1, 1),
                                "y1": round(y1, 1),
                                "x2": round(x2, 1),
                                "y2": round(y2, 1),
                            },
                        }
                    )

            return {
                "result": detections,
                "count": len(detections),
                "engine": "yolo",
                "task": "detect",
                "model": "yolo11n",
            }
        except Exception as e:
            return {"error": f"YOLO detection failed: {e}", "engine": "yolo", "task": task}
