"""RBAC + ABAC hybrid permission system."""

from dataclasses import dataclass
from typing import Any

# --- RBAC: Static role -> permission mapping ---
# Covers all 10 core modules
ROLE_PERMISSIONS: dict[str, list[str]] = {
    "admin": ["*"],
    "user": [
        "finance.read",
        "finance.write",
        "taskflow.read",
        "taskflow.write",
        "ideagraph.read",
        "ideagraph.write",
        "intelflow.read",
        "intelflow.write",
        "memvault.read",
        "memvault.write",
        "skillpath.read",
        "skillpath.write",
        "workpool.read",
        "workpool.write",
        "matchcore.read",
        "matchcore.write",
        "notification.read",
        "notification.write",
        "invest.read",
        "invest.write",
        "capture.read",
        "capture.write",
        "dailyos.read",
        "dailyos.write",
        "briefing.read",
        "briefing.write",
        "nodeflow.read",
        "nodeflow.write",
        "paper.read",
        "paper.write",
        "assistant.read",
        "plugin.use",
        "profile.read",
        "profile.write",
    ],
    "guest": [
        "finance.read",
        "taskflow.read",
        "ideagraph.read",
        "intelflow.read",
        "memvault.read",
        "capture.read",
        "dailyos.read",
        "briefing.read",
        "nodeflow.read",
        "paper.read",
        "assistant.read",
    ],
}


def has_permission(role: str, permission: str) -> bool:
    perms = ROLE_PERMISSIONS.get(role, [])
    if "*" in perms:
        return True
    for p in perms:
        if p == permission:
            return True
        if p.endswith(".*") and permission.startswith(p[:-2]):
            return True
    return False


# --- ABAC: Dynamic attribute-based policies ---
@dataclass
class RequestContext:
    user_id: str
    user_role: str
    user_status: str
    resource_owner: str | None = None
    action: str = ""
    extra: dict[str, Any] | None = None


class PolicyEngine:
    def __init__(self):
        self._policies: list[dict] = []

    def add_policy(self, name: str, effect: str, condition):
        self._policies.append({"name": name, "effect": effect, "condition": condition})

    def evaluate(self, ctx: RequestContext) -> tuple[bool, str]:
        # RBAC check first
        if not has_permission(ctx.user_role, ctx.action):
            return False, f"RBAC denied: role '{ctx.user_role}' lacks '{ctx.action}'"

        # ABAC policies
        for policy in self._policies:
            if policy["condition"](ctx):
                if policy["effect"] == "deny":
                    return False, f"ABAC denied: policy '{policy['name']}'"

        return True, "allowed"


# Default policies
policy_engine = PolicyEngine()
policy_engine.add_policy(
    "suspended_users_blocked",
    "deny",
    lambda ctx: ctx.user_status in ("suspended", "banned"),
)
policy_engine.add_policy(
    "owner_only_write",
    "deny",
    lambda ctx: (
        ctx.action.endswith(".write")
        and ctx.resource_owner is not None
        and ctx.resource_owner != ctx.user_id
        and ctx.user_role != "admin"
    ),
)
