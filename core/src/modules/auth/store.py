"""Auth state management — FeatureStore + NgRx patterns.

Tracks active sessions, recent logins, login count, and user status changes.
Does NOT replicate DB — thin reactive layer on top of services.py.
"""

from __future__ import annotations

from src.shared.actions import create_action, create_reducer, on
from src.shared.immutable_utils import batch_update, to_immutable, update_in
from src.shared.middleware import AuditMiddleware
from src.shared.selectors import create_selector
from src.shared.store import FeatureStore

# ── 1. Actions ────────────────────────────────────────────────────────────

UserRegistered = create_action("auth.user.registered")
UserLoggedIn = create_action("auth.user.logged_in")
UserLoggedOut = create_action("auth.user.logged_out")
UserStatusChanged = create_action("auth.user.status_changed")
RoleAssigned = create_action("auth.role.assigned")
OAuthLinked = create_action("auth.oauth.linked")
SessionCreated = create_action("auth.session.created")
SessionRevoked = create_action("auth.session.revoked")

# ── 2. Reducer ────────────────────────────────────────────────────────────

_MAX_RECENT = 50


def _handle_user_logged_in(state, action):
    """Track login: prepend to recent_logins (capped) + increment login_count."""
    payload = action.payload or {}
    user_id = payload.get("user_id")
    if not user_id:
        return state

    recent = state.get("recent_logins", ())
    entry = to_immutable(
        {
            "user_id": user_id,
            "email": payload.get("email"),
            "timestamp": payload.get("timestamp"),
            "ip": payload.get("ip"),
        }
    )
    new_recent = (entry, *recent)[:_MAX_RECENT]
    return batch_update(
        state,
        {
            "recent_logins": new_recent,
            "login_count": state["login_count"] + 1,
        },
    )


def _handle_user_logged_out(state, action):
    """Remove session from active_sessions on logout."""
    payload = action.payload or {}
    session_id = payload.get("session_id")
    if not session_id:
        return state
    sessions = state.get("active_sessions", {})
    if session_id not in sessions:
        return state
    e = sessions.mutate()
    del e[session_id]
    return state.set("active_sessions", e.finish())


def _handle_session_created(state, action):
    """Add new session to active_sessions map."""
    payload = action.payload or {}
    session_id = payload.get("session_id") or payload.get("id")
    if not session_id:
        return state
    sessions = state.get("active_sessions", {})
    session_entry = to_immutable(
        {
            "session_id": session_id,
            "user_id": payload.get("user_id"),
            "created_at": payload.get("created_at"),
            "expires_at": payload.get("expires_at"),
        }
    )
    return update_in(state, ["active_sessions"], lambda _: sessions.set(session_id, session_entry))


def _handle_session_revoked(state, action):
    """Remove session from active_sessions."""
    payload = action.payload or {}
    session_id = payload.get("session_id") or payload.get("id")
    if not session_id:
        return state
    sessions = state.get("active_sessions", {})
    if session_id not in sessions:
        return state
    e = sessions.mutate()
    del e[session_id]
    return state.set("active_sessions", e.finish())


def _handle_user_status_changed(state, action):
    """Track user status transitions in status_history (capped at 50)."""
    payload = action.payload or {}
    user_id = payload.get("user_id")
    if not user_id:
        return state
    history = state.get("status_history", ())
    entry = to_immutable(
        {
            "user_id": user_id,
            "old_status": payload.get("old_status"),
            "new_status": payload.get("new_status"),
            "timestamp": payload.get("timestamp"),
        }
    )
    new_history = (entry, *history)[:_MAX_RECENT]
    return state.set("status_history", new_history)


auth_reducer = create_reducer(
    {
        "active_sessions": {},
        "recent_logins": [],
        "login_count": 0,
        "status_history": [],
    },
    on(UserLoggedIn, _handle_user_logged_in),
    on(UserLoggedOut, _handle_user_logged_out),
    on(SessionCreated, _handle_session_created),
    on(SessionRevoked, _handle_session_revoked),
    on(UserStatusChanged, _handle_user_status_changed),
    on(UserRegistered, lambda s, a: s),
    on(RoleAssigned, lambda s, a: s),
    on(OAuthLinked, lambda s, a: s),
)

# ── 3. Selectors ─────────────────────────────────────────────────────────

select_active_sessions = create_selector(lambda s: s["active_sessions"])
select_login_count = create_selector(lambda s: s["login_count"])
select_recent_logins = create_selector(lambda s: s["recent_logins"])
select_status_history = create_selector(lambda s: s["status_history"])
select_active_session_count = create_selector(
    select_active_sessions,
    result_fn=lambda sessions: len(sessions),
)

# ── 4. Store ──────────────────────────────────────────────────────────────

_AUDIT_TYPES = {
    UserRegistered.type,
    UserLoggedIn.type,
    UserLoggedOut.type,
    UserStatusChanged.type,
    RoleAssigned.type,
    OAuthLinked.type,
    SessionCreated.type,
    SessionRevoked.type,
}

auth_store: FeatureStore = FeatureStore(
    "auth",
    auth_reducer,
    middlewares=[AuditMiddleware(audit_types=_AUDIT_TYPES)],
)
