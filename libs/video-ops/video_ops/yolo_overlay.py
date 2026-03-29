"""YOLO-overlay operator -- draw object detection bounding boxes on video frames."""

from __future__ import annotations

import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from . import register

logger = logging.getLogger(__name__)


@register("yolo-overlay")
class YoloOverlayOp:
    """Run YOLO detection on each frame and draw bounding boxes.

    Calls the Vision station HTTP API (``POST /analyze?task=detect&engine=yolo``)
    for each frame, then draws bounding boxes and labels using cv2 (with
    Pillow as fallback).

    Frames are processed in parallel via :class:`ThreadPoolExecutor`, but
    *workers* is kept low (default 2) to avoid overwhelming the vision
    station.

    Requires ``frames_dir`` and ``frame_count`` in ctx (typically from
    :class:`ExtractFramesOp`).
    """

    name = "yolo-overlay"
    input_keys = ("frames_dir", "frame_count")
    output_keys = ("frames_dir",)
    mode = "batch"

    def __init__(
        self,
        engine: str = "yolo",
        station_url: str = "http://127.0.0.1:10203",
        confidence_threshold: float = 0.5,
        box_color: tuple = (0, 255, 0),
        text_color: tuple = (255, 255, 255),
        thickness: int = 2,
        workers: int = 2,
    ):
        self.engine = str(engine)
        self.station_url = str(station_url).rstrip("/")
        self.confidence_threshold = float(confidence_threshold)
        self.box_color = tuple(int(c) for c in box_color)
        self.text_color = tuple(int(c) for c in text_color)
        self.thickness = int(thickness)
        self.workers = int(workers)

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        frames_dir = ctx["frames_dir"]
        _ = ctx["frame_count"]  # validate key exists

        frame_files = sorted(
            f for f in os.listdir(frames_dir)
            if f.startswith("frame_") and "." in f
        )

        if not frame_files:
            logger.warning("yolo-overlay: no frame files in %s", frames_dir)
            return ctx

        output_dir = tempfile.mkdtemp(prefix="yolo-overlay-")

        total_detections = 0
        completed = 0
        errors = 0

        def _process_frame(frame_name: str) -> int:
            """Process one frame: detect + draw. Returns detection count."""
            input_path = os.path.join(frames_dir, frame_name)
            output_path = os.path.join(output_dir, frame_name)

            # Call vision station
            detections = self._detect(input_path)

            # Filter by confidence
            detections = [
                d for d in detections
                if d.get("confidence", 0) >= self.confidence_threshold
            ]

            # Load image, draw boxes, save
            img = _load_image(input_path)
            if img is None:
                # Copy original on failure
                import shutil
                shutil.copy2(input_path, output_path)
                return 0

            for det in detections:
                bbox = det.get("bbox", {})
                x1 = int(bbox.get("x1", 0))
                y1 = int(bbox.get("y1", 0))
                x2 = int(bbox.get("x2", 0))
                y2 = int(bbox.get("y2", 0))
                label = det.get("class", "?")
                conf = det.get("confidence", 0)
                text = f"{label} {conf:.2f}"

                _draw_box(
                    img, x1, y1, x2, y2, text,
                    self.box_color, self.text_color, self.thickness,
                )

            _save_image(output_path, img)
            return len(detections)

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {
                pool.submit(_process_frame, fname): fname
                for fname in frame_files
            }
            for future in as_completed(futures):
                try:
                    det_count = future.result()
                    total_detections += det_count
                except Exception as exc:
                    errors += 1
                    fname = futures[future]
                    logger.warning("yolo-overlay: failed on %s: %s", fname, exc)
                    # Copy original frame on error
                    src = os.path.join(frames_dir, fname)
                    dst = os.path.join(output_dir, fname)
                    try:
                        import shutil
                        shutil.copy2(src, dst)
                    except OSError:
                        pass

                completed += 1
                if completed % 50 == 0:
                    logger.info(
                        "yolo-overlay: %d/%d frames processed",
                        completed, len(frame_files),
                    )

        ctx["frames_dir"] = output_dir

        logger.info(
            "yolo-overlay: %d frames processed, %d total detections, %d errors "
            "(engine=%s, threshold=%.2f, workers=%d)",
            len(frame_files),
            total_detections,
            errors,
            self.engine,
            self.confidence_threshold,
            self.workers,
        )

        return ctx

    # -- HTTP detection --------------------------------------------------------

    def _detect(self, image_path: str) -> list[dict]:
        """Call vision station detect API. Returns list of detection dicts."""
        try:
            import httpx
        except ImportError:
            logger.error("yolo-overlay: httpx not installed, cannot call vision station")
            return []

        url = f"{self.station_url}/analyze"
        params = {
            "path": image_path,
            "task": "detect",
            "engine": self.engine,
        }

        try:
            resp = httpx.post(url, params=params, timeout=30.0)
            resp.raise_for_status()
            data = resp.json()
            return data.get("result", [])
        except httpx.TimeoutException:
            logger.warning("yolo-overlay: vision station timeout for %s", image_path)
            return []
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "yolo-overlay: vision station HTTP %d for %s",
                exc.response.status_code, image_path,
            )
            return []
        except Exception as exc:
            logger.warning("yolo-overlay: vision station error: %s", exc)
            return []


# -- Image I/O helpers (cv2 preferred, Pillow fallback) -------------------------


def _load_image(path: str):
    """Load image as numpy array (BGR). Tries cv2 first, Pillow fallback."""
    try:
        import cv2
        return cv2.imread(path)
    except ImportError:
        pass
    try:
        import numpy as np
        from PIL import Image
        img = Image.open(path).convert("RGB")
        return np.array(img)[:, :, ::-1]  # RGB -> BGR
    except ImportError:
        logger.error("yolo-overlay: neither cv2 nor Pillow available")
        return None


def _save_image(path: str, img) -> None:
    """Save numpy array image. Tries cv2 first, Pillow fallback."""
    try:
        import cv2
        cv2.imwrite(path, img)
        return
    except ImportError:
        pass
    try:
        from PIL import Image
        rgb = img[:, :, ::-1] if img.ndim == 3 and img.shape[2] == 3 else img
        Image.fromarray(rgb).save(path)
    except ImportError:
        logger.error("yolo-overlay: cannot save image, no cv2 or Pillow")


def _draw_box(
    img,
    x1: int, y1: int, x2: int, y2: int,
    text: str,
    box_color: tuple,
    text_color: tuple,
    thickness: int,
) -> None:
    """Draw bounding box + label on image. cv2 preferred, Pillow fallback."""
    try:
        import cv2
        cv2.rectangle(img, (x1, y1), (x2, y2), box_color, thickness)
        # Text background
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(img, (x1, y1 - th - 6), (x1 + tw + 4, y1), box_color, -1)
        cv2.putText(
            img, text, (x1 + 2, y1 - 4),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, text_color, 1, cv2.LINE_AA,
        )
        return
    except ImportError:
        pass
    try:
        import numpy as np
        from PIL import Image, ImageDraw, ImageFont
        pil_img = Image.fromarray(img[:, :, ::-1])  # BGR -> RGB
        draw = ImageDraw.Draw(pil_img)
        pil_box_color = (box_color[2], box_color[1], box_color[0])  # BGR -> RGB
        pil_text_color = (text_color[2], text_color[1], text_color[0])
        draw.rectangle([x1, y1, x2, y2], outline=pil_box_color, width=thickness)
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
        except OSError:
            font = ImageFont.load_default()
        draw.text((x1 + 2, y1 - 16), text, fill=pil_text_color, font=font)
        result = np.array(pil_img)[:, :, ::-1]  # RGB -> BGR
        img[:] = result
    except ImportError:
        logger.warning("yolo-overlay: no drawing library available, skipping box draw")
