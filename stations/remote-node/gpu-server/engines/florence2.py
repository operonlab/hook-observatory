"""Florence-2-large GPU engine.

Provides segmentation, detection, captioning and batch-segmentation via
Microsoft's Florence-2-large model running in float16 on CUDA.
"""

from __future__ import annotations

import gc
import logging
import time
import threading
from typing import Any

import torch
from PIL import Image

log = logging.getLogger("gpu-server.florence2")

MODEL_ID = "microsoft/Florence-2-large"
APPROX_VRAM_MB = 4200  # ~4.2 GB in fp16


class Florence2Engine:
    """Lazy-loaded Florence-2-large engine."""

    def __init__(self) -> None:
        self._model: Any | None = None
        self._processor: Any | None = None
        self._last_used: float = 0.0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # GPUEngine protocol
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "florence2"

    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        """Load model + processor onto CUDA in float16."""
        if self._model is not None:
            return

        with self._lock:
            # Double-check after acquiring lock
            if self._model is not None:
                return

            log.info("Loading Florence-2-large (%s) onto CUDA fp16 ...", MODEL_ID)
            from transformers import AutoModelForCausalLM, AutoProcessor

            self._processor = AutoProcessor.from_pretrained(
                MODEL_ID, trust_remote_code=True
            )
            self._model = AutoModelForCausalLM.from_pretrained(
                MODEL_ID,
                torch_dtype=torch.float16,
                trust_remote_code=True,
            ).to("cuda")
            self._model.eval()
            self._last_used = time.time()
            log.info("Florence-2-large loaded successfully.")

    def unload(self) -> None:
        """Release model from GPU memory."""
        with self._lock:
            if self._model is None:
                return
            log.info("Unloading Florence-2-large ...")
            del self._model
            del self._processor
            self._model = None
            self._processor = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            log.info("Florence-2-large unloaded, VRAM freed.")

    def last_used(self) -> float:
        return self._last_used

    def vram_mb(self) -> int:
        return APPROX_VRAM_MB if self.is_loaded() else 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if not self.is_loaded():
            self.load()

    def _run_inference(
        self, image: Image.Image, task_prompt: str, text_input: str = ""
    ) -> dict:
        """Run a single Florence-2 inference and return the parsed result."""
        self._ensure_loaded()
        self._last_used = time.time()

        prompt = task_prompt if not text_input else task_prompt + text_input

        inputs = self._processor(
            text=prompt, images=image, return_tensors="pt"
        )
        # Move all tensors to CUDA fp16
        inputs = {
            k: v.to("cuda", dtype=torch.float16)
            if v.dtype in (torch.float32, torch.float64)
            else v.to("cuda")
            for k, v in inputs.items()
        }

        with torch.inference_mode():
            generated_ids = self._model.generate(
                **inputs,
                max_new_tokens=1024,
                num_beams=3,
            )

        generated_text = self._processor.batch_decode(
            generated_ids, skip_special_tokens=False
        )[0]

        parsed = self._processor.post_process_generation(
            generated_text,
            task=task_prompt,
            image_size=(image.width, image.height),
        )
        return parsed

    # ------------------------------------------------------------------
    # Public inference methods
    # ------------------------------------------------------------------

    def segment(self, image: Image.Image, prompt: str) -> dict:
        """Referring Expression Segmentation.

        Returns ``{"polygons": [...], "labels": [prompt]}``.
        Each polygon is a flat list ``[x1, y1, x2, y2, ...]`` in pixel coords.
        """
        task = "<REFERRING_EXPRESSION_SEGMENTATION>"
        raw = self._run_inference(image, task, prompt)
        result = raw.get(task, {})

        polygons_raw = result.get("polygons", [])
        # Flatten nested structures — Florence-2 may return list-of-list-of-coords
        polygons: list[list[float]] = []
        for poly_group in polygons_raw:
            if isinstance(poly_group, list):
                # Could be [[x1,y1,x2,y2,...]] or [[[x1,y1],[x2,y2],...]]
                if poly_group and isinstance(poly_group[0], list):
                    for sub in poly_group:
                        flat = [coord for pt in sub for coord in (pt if isinstance(pt, (list, tuple)) else [pt])]
                        polygons.append(flat)
                else:
                    polygons.append(poly_group)

        return {"polygons": polygons, "labels": [prompt]}

    def detect(self, image: Image.Image, prompt: str) -> dict:
        """Open-vocabulary object detection.

        Returns ``{"boxes": [[x1,y1,x2,y2], ...], "labels": [...], "scores": [...]}``.
        """
        # Use open-vocabulary detection when a text prompt is provided
        task = "<OPEN_VOCABULARY_DETECTION>"
        raw = self._run_inference(image, task, prompt)
        result = raw.get(task, {})

        boxes = result.get("bboxes", [])
        labels = result.get("bboxes_labels", result.get("labels", []))

        # Florence-2 OVD does not return scores — fill with 1.0
        scores = [1.0] * len(boxes)

        return {
            "boxes": [[float(c) for c in box] for box in boxes],
            "labels": list(labels),
            "scores": scores,
        }

    def caption(self, image: Image.Image, detail: str = "brief") -> dict:
        """Image captioning.

        *detail*: ``"brief"`` or ``"detailed"``.
        Returns ``{"caption": str}``.
        """
        task = "<CAPTION>" if detail == "brief" else "<DETAILED_CAPTION>"
        raw = self._run_inference(image, task)
        text = raw.get(task, "")
        return {"caption": text}

    def batch_segment(self, image: Image.Image, prompts: list[str]) -> dict:
        """Run segmentation for multiple prompts on the same image.

        Returns ``{"results": {prompt: {"polygons": [...]}}}`` for each prompt.
        """
        results: dict[str, dict] = {}
        for prompt in prompts:
            results[prompt] = self.segment(image, prompt)
        return {"results": results}
