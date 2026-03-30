"""Admin state management — FeatureStore + NgRx patterns.

Tracks audit log (in-memory recent), module states, and soft-delete counts.
Does NOT replicate DB — thin reactive layer on top of services.py.
"""

from __future__ import annotations

from src.shared.actions import create_action, create_reducer, on
from src.shared.immutable_utils import batch_update, to_immutable, update_in
from src.shared.middleware import AuditMiddleware
from src.shared.selectors import create_selector
from src.shared.store import FeatureStore

# ── 1. Actions ────────────────────────────────────────────────────────────

HealthChecked = create_action("admin.health.checked")
UserManaged = create_action("admin.user.managed")
ModuleToggled = create_action("admin.module.toggled")
ConfigUpdated = create_action("admin.config.updated")
EntitySoftDeleted = create_action("admin.entity.soft_deleted")
EntityRestored = create_action("admin.entity.restored")
EntityPurged = create_action("admin.entity.purged")

# ── 2. Reducer ────────────────────────────────────────────────────────────

_MAX_AUDIT_LOG = 50


def _handle_entity_soft_deleted(state, action):
    payload = action.payload or {}
    audit_log = state.get("audit_log", ())
    entry = to_immutable(
        {
            "action": "soft_deleted",
            "module": payload.get("module"),
            "entity_type": payload.get("entity_type"),
            "entity_id": payload.get("entity_id"),
            "user_id": payload.get("user_id"),
            "timestamp": payload.get("timestamp"),
        }
    )
    new_log = (entry, *audit_log)[:_MAX_AUDIT_LOG]
    return batch_update(
        state,
        {
            "audit_log": new_log,
            "soft_deleted_count": state["soft_deleted_count"] + 1,
        },
    )


def _handle_entity_restored(state, action):
    payload = action.payload or {}
    audit_log = state.get("audit_log", ())
    entry = to_immutable(
        {
            "action": "restored",
            "module": payload.get("module"),
            "entity_type": payload.get("entity_type"),
            "entity_id": payload.get("entity_id"),
            "user_id": payload.get("user_id"),
            "timestamp": payload.get("timestamp"),
        }
    )
    new_log = (entry, *audit_log)[:_MAX_AUDIT_LOG]
    return batch_update(
        state,
        {
            "audit_log": new_log,
            "soft_deleted_count": max(0, state["soft_deleted_count"] - 1),
        },
    )


def _handle_entity_purged(state, action):
    payload = action.payload or {}
    audit_log = state.get("audit_log", ())
    entry = to_immutable(
        {
            "action": "purged",
            "module": payload.get("module"),
            "entity_type": payload.get("entity_type"),
            "entity_id": payload.get("entity_id"),
            "user_id": payload.get("user_id"),
            "timestamp": payload.get("timestamp"),
        }
    )
    new_log = (entry, *audit_log)[:_MAX_AUDIT_LOG]
    return state.set("audit_log", new_log)


def _handle_config_updated(state, action):
    payload = action.payload or {}
    audit_log = state.get("audit_log", ())
    entry = to_immutable(
        {
            "action": "config_updated",
            "key": payload.get("key"),
            "user_id": payload.get("user_id"),
            "timestamp": payload.get("timestamp"),
        }
    )
    new_log = (entry, *audit_log)[:_MAX_AUDIT_LOG]
    return state.set("audit_log", new_log)


def _handle_module_toggled(state, action):
    payload = action.payload or {}
    module_name = payload.get("module")
    enabled = payload.get("enabled")
    if not module_name:
        return state
    module_states = state.get("module_states", {})
    return update_in(
        state,
        ["module_states"],
        lambda _: module_states.set(
            module_name, to_immutable({"enabled": enabled, "toggled_at": payload.get("timestamp")})
        ),
    )


admin_reducer = create_reducer(
    {
        "audit_log": [],
        "module_states": {},
        "soft_deleted_count": 0,
    },
    on(EntitySoftDeleted, _handle_entity_soft_deleted),
    on(EntityRestored, _handle_entity_restored),
    on(EntityPurged, _handle_entity_purged),
    on(ConfigUpdated, _handle_config_updated),
    on(ModuleToggled, _handle_module_toggled),
    on(HealthChecked, lambda s, a: s),
    on(UserManaged, lambda s, a: s),
)

# ── 3. Selectors ─────────────────────────────────────────────────────────

select_audit_log = create_selector(lambda s: s["audit_log"])
select_module_states = create_selector(lambda s: s["module_states"])
select_soft_deleted_count = create_selector(lambda s: s["soft_deleted_count"])
select_enabled_modules = create_selector(
    select_module_states,
    result_fn=lambda modules: {k: v for k, v in modules.items() if v.get("enabled")},
)

# ── 4. Store ──────────────────────────────────────────────────────────────

_AUDIT_TYPES = {
    HealthChecked.type,
    UserManaged.type,
    ModuleToggled.type,
    ConfigUpdated.type,
    EntitySoftDeleted.type,
    EntityRestored.type,
    EntityPurged.type,
}

admin_store: FeatureStore = FeatureStore(
    "admin",
    admin_reducer,
    middlewares=[AuditMiddleware(audit_types=_AUDIT_TYPES)],
)
