"""Memvault Reactive Operators — composable pipeline stages.

All operators implement the async Operator protocol from
core/src/shared/reactive.py (name, input_keys, output_keys, async __call__).

Base class: MemvaultOp (toggle + error isolation + timing).
"""

from ._base import MemvaultOp, PipelineMeta

__all__ = [
    "MemvaultOp",
    "PipelineMeta",
]
