"""Auth actions — type-safe event definitions."""

from src.shared.actions import create_action

# ── Actions ──────────────────────────────────────────────────────────────

UserRegistered = create_action("auth.user.registered")
UserLoggedIn = create_action("auth.user.logged_in")
UserLoggedOut = create_action("auth.user.logged_out")
UserStatusChanged = create_action("auth.user.status_changed")
RoleAssigned = create_action("auth.role.assigned")
OAuthLinked = create_action("auth.oauth.linked")
SessionCreated = create_action("auth.session.created")
SessionRevoked = create_action("auth.session.revoked")
