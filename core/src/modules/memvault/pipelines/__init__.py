"""Memvault pipeline factories — composable Pipeline builders.

Each factory returns a Pipeline (from core/src/shared/reactive.py)
configured with MemvaultOps and validated via compile().
"""

from .dream_pipeline import build_dream_pipeline
from .lint_pipeline import build_lint_pipeline

__all__ = [
    "build_dream_pipeline",
    "build_lint_pipeline",
]
