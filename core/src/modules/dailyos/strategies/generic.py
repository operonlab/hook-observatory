"""GenericStrategy — config-driven default strategy for all methods."""

from __future__ import annotations

from .base import MethodStrategy


class GenericStrategy(MethodStrategy):
    """Config-driven strategy — handles all methods via config fields.

    Most methods don't need a custom subclass; GenericStrategy reads config
    and applies the rules. Custom subclasses only for truly unique logic.
    """

    def validate_plan(self, items: list[dict]) -> list[str]:
        errors: list[str] = []
        max_items = self.config.get("max_items")
        if max_items and len(items) > max_items:
            errors.append(f"Plan exceeds maximum of {max_items} items (has {len(items)})")

        categories = self.config.get("categories", [])
        for cat in categories:
            cat_items = [i for i in items if i.get("category") == cat["id"]]
            if cat.get("max_items") and len(cat_items) > cat["max_items"]:
                errors.append(f"Category '{cat['name']}' exceeds limit of {cat['max_items']}")
            if cat.get("min_items", 0) > len(cat_items):
                errors.append(f"Category '{cat['name']}' needs at least {cat['min_items']} items")

        return errors

    def sort_items(self, items: list[dict]) -> list[dict]:
        ordering = self.config.get("ordering", "free")
        if ordering == "sequential":
            return sorted(items, key=lambda i: i.get("sort_order", 0))
        elif ordering == "priority":
            priority_map = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
            return sorted(items, key=lambda i: priority_map.get(i.get("priority", "medium"), 2))
        elif ordering == "time":
            return sorted(items, key=lambda i: i.get("scheduled_time") or "99:99")
        elif ordering == "category":
            cat_order = {c["id"]: c.get("sort_order", 0) for c in self.config.get("categories", [])}
            return sorted(
                items,
                key=lambda i: (cat_order.get(i.get("category"), 99), i.get("sort_order", 0)),
            )
        return items  # "free" — preserve user order

    def suggest_frog(self, items: list[dict]) -> list[str]:
        frog_config = self.config.get("frog", {})
        if not frog_config.get("enabled"):
            return []

        count = frog_config.get("count", 1)
        criteria = frog_config.get("suggest_criteria", {})

        # Score each item
        scored: list[tuple[str, float]] = []
        for item in items:
            if item.get("status") in ("done", "cancelled"):
                continue
            score = 0.0
            if criteria.get("prefer_high_priority"):
                prio_score = {"urgent": 4, "high": 3, "medium": 1, "low": 0}
                score += prio_score.get(item.get("priority", "medium"), 1)
            if criteria.get("prefer_dreaded"):
                age_days = item.get("age_days", 0)
                max_age = criteria.get("max_age_days", 7)
                score += min(age_days / max_age, 1.0) * 3
            if criteria.get("prefer_high_impact"):
                score += min(item.get("subtask_count", 0), 5) * 0.5
            scored.append((item.get("id", ""), score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [item_id for item_id, _ in scored[:count]]

    def check_completion(self, items: list[dict]) -> tuple[bool, float]:
        rule = self.config.get("completion_rule", {})
        mode = rule.get("mode", "percentage")

        if not items:
            return (True, 1.0)

        done = [i for i in items if i.get("status") == "done"]
        done_ratio = len(done) / len(items)

        if mode == "all":
            return (len(done) == len(items), done_ratio)

        threshold = rule.get("threshold", 0.8)

        if mode == "frog_plus_percentage":
            frog_items = [i for i in items if i.get("is_frog")]
            frogs_done = all(f.get("status") == "done" for f in frog_items)
            non_frog = [i for i in items if not i.get("is_frog")]
            non_frog_done = [i for i in non_frog if i.get("status") == "done"]
            nf_ratio = len(non_frog_done) / len(non_frog) if non_frog else 1.0
            is_complete = frogs_done and nf_ratio >= threshold
            overall = done_ratio
            return (is_complete, overall)

        if mode == "weighted":
            categories = {
                c["id"]: c.get("priority_weight", 1)
                for c in self.config.get("categories", [])
            }
            total_weight = sum(categories.get(i.get("category"), 1) for i in items)
            done_weight = sum(categories.get(i.get("category"), 1) for i in done)
            weighted_ratio = done_weight / total_weight if total_weight else 1.0
            return (weighted_ratio >= threshold, weighted_ratio)

        # percentage mode (default)
        return (done_ratio >= threshold, done_ratio)

    def handle_overflow(self, items: list[dict]) -> dict[str, list[dict]]:
        overflow_config = self.config.get("overflow", {})
        mode = overflow_config.get("mode", "carry_forward")
        max_carry = overflow_config.get("max_carry_days", 3)
        stale_days = overflow_config.get("stale_warning_days", 2)

        incomplete = [i for i in items if i.get("status") not in ("done", "cancelled")]

        result: dict[str, list[dict]] = {"carry": [], "stale": [], "drop": []}
        for item in incomplete:
            carry_count = item.get("carry_count", 0)
            if mode == "drop":
                result["drop"].append(item)
            elif mode == "backlog":
                result["drop"].append(item)  # moved to backlog externally
            elif max_carry and carry_count >= max_carry:
                result["stale"].append(item)
            elif carry_count >= stale_days:
                item["carry_count"] = carry_count + 1
                result["stale"].append(item)
            else:
                item["carry_count"] = carry_count + 1
                result["carry"].append(item)

        return result
