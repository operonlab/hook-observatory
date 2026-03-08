"""MethodStrategy ABC — base class for method-specific behavior."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, timedelta
from typing import Any


class MethodStrategy(ABC):
    """Base class for method-specific behavior.

    Each strategy is stateless — all state comes from config + plan items.
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> MethodStrategy:
        """Factory: pick strategy subclass based on config shape.

        Falls back to GenericStrategy which handles everything via config.
        """
        from .registry import get_strategy_class

        strategy_cls = get_strategy_class(config)
        return strategy_cls(config)

    # --- Validation ---

    @abstractmethod
    def validate_plan(self, items: list[dict]) -> list[str]:
        """Return list of validation error messages. Empty = valid."""
        ...

    # --- Ordering ---

    @abstractmethod
    def sort_items(self, items: list[dict]) -> list[dict]:
        """Sort/organize items according to method rules. Returns new list."""
        ...

    # --- Frog/MIT ---

    @abstractmethod
    def suggest_frog(self, items: list[dict]) -> list[str]:
        """Return IDs of suggested frog/MIT items."""
        ...

    # --- Completion ---

    @abstractmethod
    def check_completion(self, items: list[dict]) -> tuple[bool, float]:
        """Check if the day meets completion criteria.
        Returns (is_complete, score 0.0-1.0).
        """
        ...

    # --- Overflow ---

    @abstractmethod
    def handle_overflow(self, items: list[dict]) -> dict[str, list[dict]]:
        """Categorize incomplete items for migration.
        Returns {"carry": [...], "stale": [...], "drop": [...]}.
        """
        ...

    # --- Category Assignment ---

    def assign_category(self, item: dict) -> str | None:
        """Suggest a category for an item based on accept_filter rules."""
        categories = self.config.get("categories", [])
        for cat in sorted(categories, key=lambda c: c.get("sort_order", 0)):
            filt = cat.get("accept_filter", {})
            if self._matches_filter(item, filt):
                return cat["id"]
        return None

    def _matches_filter(self, item: dict, filt: dict) -> bool:
        if not filt:
            return True
        if "priority" in filt and item.get("priority") not in filt["priority"]:
            return False
        if "estimated_hours_gte" in filt:
            est = item.get("estimated_hours") or 0
            if est < filt["estimated_hours_gte"]:
                return False
        if "estimated_hours_lte" in filt:
            est = item.get("estimated_hours") or 0
            if est > filt["estimated_hours_lte"]:
                return False

        # due_date_within_days: item's due_date is within N days from now
        if "due_date_within_days" in filt:
            due_str = item.get("due_date")
            if not due_str:
                return False
            try:
                due = date.fromisoformat(due_str[:10])  # handle datetime isoformat too
            except (ValueError, TypeError):
                return False
            deadline = date.today() + timedelta(days=filt["due_date_within_days"])
            if due > deadline:
                return False

        # has_due_date: filter items that have/don't have a due date
        if "has_due_date" in filt:
            has_due = item.get("due_date") is not None
            if has_due != filt["has_due_date"]:
                return False

        # source: filter by source (personal/family/company)
        if "source" in filt:
            if item.get("source") not in filt["source"]:
                return False

        # tags_include: item must have at least one of these tags
        if "tags_include" in filt:
            item_tags = set(item.get("tags") or [])
            required_tags = set(filt["tags_include"])
            if not item_tags & required_tags:
                return False

        return True
