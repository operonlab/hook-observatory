"""Map-frames operator — bridge between video-ops and image-ops.

Applies an image-ops pipeline to every frame in a frames directory,
using thread-pool parallelism for throughput.
"""

from __future__ import annotations

import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from . import register

logger = logging.getLogger(__name__)


@register("map-frames")
class MapFramesOp:
    """Apply image-ops pipeline to each extracted frame.

    This is the key bridge operator that connects video-ops to image-ops.
    It takes a ``frames_dir`` full of numbered PNGs, runs each through
    an image-ops pipeline, and writes results to a new output directory.

    The ``image_ops`` spec uses ``|`` as separator (since ``,`` is used
    by the video-ops parser).  Example: ``"grayscale|clahe|contrast:alpha=1.5"``

    If ``image_ops`` is empty, this operator is a no-op and returns
    ctx unchanged.
    """

    name = "map-frames"
    input_keys = ("frames_dir", "frame_count")
    output_keys = ("frames_dir",)
    mode = "batch"

    def __init__(self, image_ops: str = "", workers: int = 4):
        self.image_ops_spec = str(image_ops)
        self.workers = int(workers)

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        if not self.image_ops_spec:
            logger.debug("map-frames: empty image_ops spec, skipping (no-op)")
            return ctx

        # Lazy import to avoid hard dependency when image_ops not installed
        from image_ops import ImagePipe, parse_operators

        ops = parse_operators(self.image_ops_spec, sep="|")
        if not ops:
            return ctx

        frames_dir = ctx["frames_dir"]
        _ = ctx["frame_count"]  # validate key exists

        # Collect and sort frames naturally
        frame_files = sorted(
            f for f in os.listdir(frames_dir) if f.startswith("frame_") and "." in f
        )

        if not frame_files:
            logger.warning("map-frames: no frame files found in %s", frames_dir)
            return ctx

        # Detect extension
        ext = frame_files[0].rsplit(".", 1)[1]

        # Create output directory
        output_dir = tempfile.mkdtemp(prefix="mapped-frames-")

        def _process_frame(frame_name: str) -> str:
            """Process a single frame through the image pipeline."""
            input_path = os.path.join(frames_dir, frame_name)
            output_path = os.path.join(output_dir, frame_name)

            img = _load_image(input_path)
            if img is None:
                raise ValueError(f"Failed to load frame: {input_path}")

            h, w = img.shape[:2]
            image_ctx: dict[str, Any] = {
                "image": img,
                "image_path": input_path,
                "width": w,
                "height": h,
                "color_space": "bgr",
            }

            # Each thread gets its own pipeline instance
            pipeline = ImagePipe().pipe(*ops)
            image_ctx = pipeline.execute(image_ctx)

            _save_image(output_path, image_ctx["image"], ext)

            return frame_name

        # Process frames in parallel
        completed = 0
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {pool.submit(_process_frame, fname): fname for fname in frame_files}
            for future in as_completed(futures):
                future.result()  # Raise on error
                completed += 1
                if completed % 100 == 0:
                    logger.info(
                        "map-frames: %d/%d frames processed",
                        completed,
                        len(frame_files),
                    )

        ctx["frames_dir"] = output_dir

        logger.info(
            "map-frames: processed %d frames with [%s] (%d workers)",
            len(frame_files),
            self.image_ops_spec,
            self.workers,
        )

        return ctx


def _load_image(path: str):
    """Load image as numpy array. Tries cv2 first, falls back to Pillow."""
    try:
        import cv2

        return cv2.imread(path)
    except ImportError:
        pass

    try:
        import numpy as np
        from PIL import Image

        img = Image.open(path)
        return np.array(img.convert("RGB"))[:, :, ::-1]  # RGB -> BGR for consistency
    except ImportError as e:
        raise ImportError(
            "map-frames requires either cv2 (opencv-python) or Pillow to load frames"
        ) from e


def _save_image(path: str, img, ext: str) -> None:
    """Save numpy array image. Tries cv2 first, falls back to Pillow."""
    try:
        import cv2

        cv2.imwrite(path, img)
        return
    except ImportError:
        pass

    try:
        from PIL import Image

        # img is BGR numpy array, convert to RGB for Pillow
        rgb = img[:, :, ::-1] if img.ndim == 3 and img.shape[2] == 3 else img
        Image.fromarray(rgb).save(path)
    except ImportError as e:
        raise ImportError(
            "map-frames requires either cv2 (opencv-python) or Pillow to save frames"
        ) from e
