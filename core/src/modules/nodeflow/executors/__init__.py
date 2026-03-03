"""Nodeflow node executors — one per node type."""

from .action import ActionExecutor
from .base import BaseNodeExecutor
from .condition import ConditionExecutor
from .delay import DelayExecutor
from .notify import NotifyExecutor
from .transform import TransformExecutor
from .trigger import TriggerExecutor

EXECUTOR_MAP: dict[str, type[BaseNodeExecutor]] = {
    "trigger": TriggerExecutor,
    "action": ActionExecutor,
    "condition": ConditionExecutor,
    "transform": TransformExecutor,
    "notify": NotifyExecutor,
    "delay": DelayExecutor,
}

__all__ = [
    "EXECUTOR_MAP",
    "ActionExecutor",
    "BaseNodeExecutor",
    "ConditionExecutor",
    "DelayExecutor",
    "NotifyExecutor",
    "TransformExecutor",
    "TriggerExecutor",
]
