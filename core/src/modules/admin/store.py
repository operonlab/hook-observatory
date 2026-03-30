"""Admin actions — type-safe event definitions."""

from src.shared.actions import create_action

# ── Actions ──────────────────────────────────────────────────────────────

HealthChecked = create_action("admin.health.checked")
UserManaged = create_action("admin.user.managed")
ModuleToggled = create_action("admin.module.toggled")
ConfigUpdated = create_action("admin.config.updated")
EntitySoftDeleted = create_action("admin.entity.soft_deleted")
EntityRestored = create_action("admin.entity.restored")
EntityPurged = create_action("admin.entity.purged")
