"""Auth state management — FeatureStore + NgRx patterns.

Tracks active sessions, recent logins, login count, and user status changes.
Does NOT replicate DB — thin reactive layer on top of services.py.
"""

from __future__ import annotations

import logging

from src.shared.actions import create_action, create_reducer, on
from src.shared.immutable_utils import batch_update, to_immutable, update_in
from src.shared.middleware import AuditMiddleware
from src.shared.selectors import create_selector
from src.shared.store import FeatureStore

logger = logging.getLogger(__name__)

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

# ── 5. Effects ────────────────────────────────────────────────────────────


@effect(UserLoggedIn, store=auth_store)
async def notify_login_effect(action, store) -> None:
    """登入成功 → 透過 EventBus 發布跨模組通知。

    讓 notification 模組可以做登入提醒（新裝置 / 異常 IP）。
    """
    payload = action.payload or {}
    user_id = payload.get("user_id")
    if not user_id:
        return

    logger.info(
        "auth.effect.user_logged_in",
        user_id=user_id,
        ip=payload.get("ip"),
        email=payload.get("email"),
    )

    try:
        from src.events.bus import Event, event_bus

        await event_bus.publish(
            Event(
                type="auth.user.logged_in.notify",
                data={
                    "user_id": user_id,
                    "email": payload.get("email"),
                    "ip": payload.get("ip"),
                    "timestamp": payload.get("timestamp"),
                },
                source="auth_store",
            )
        )
    except Exception as exc:
        logger.warning("auth.effect.notify_login_failed", error=str(exc))


@effect(UserLoggedOut, store=auth_store)
async def cleanup_session_effect(action, store) -> None:
    """登出 → 記錄 session 清理日誌，並通知跨模組做必要收尾。

    AuditMiddleware 已寫 audit log，這裡補充跨模組 EventBus 通知。
    """
    payload = action.payload or {}
    user_id = payload.get("user_id")
    session_id = payload.get("session_id")

    logger.info(
        "auth.effect.user_logged_out",
        user_id=user_id,
        session_id=session_id,
    )

    try:
        from src.events.bus import Event, event_bus

        await event_bus.publish(
            Event(
                type="auth.session.cleanup",
                data={
                    "user_id": user_id,
                    "session_id": session_id,
                },
                source="auth_store",
            )
        )
    except Exception as exc:
        logger.warning("auth.effect.cleanup_session_failed", error=str(exc))


@effect(UserStatusChanged, store=auth_store)
async def notify_status_change_effect(action, store) -> None:
    """用戶狀態變更（suspend/ban/activate）→ 跨模組廣播。

    downstream（notification、taskflow 等）可訂閱此事件做各自處理。
    """
    payload = action.payload or {}
    user_id = payload.get("user_id")
    new_status = payload.get("new_status")
    old_status = payload.get("old_status")

    logger.info(
        "auth.effect.user_status_changed",
        user_id=user_id,
        old_status=old_status,
        new_status=new_status,
    )

    try:
        from src.events.bus import Event, event_bus

        await event_bus.publish(
            Event(
                type="auth.user.status_changed.notify",
                data={
                    "user_id": user_id,
                    "old_status": old_status,
                    "new_status": new_status,
                    "timestamp": payload.get("timestamp"),
                },
                source="auth_store",
            )
        )
    except Exception as exc:
        logger.warning("auth.effect.notify_status_change_failed", error=str(exc))


@effect(UserRegistered, store=auth_store)
async def notify_registration_effect(action, store) -> None:
    """新用戶註冊 → 記錄日誌 + 廣播歡迎事件。

    notification 模組可訂閱以發送歡迎信或 onboarding 流程。
    """
    payload = action.payload or {}
    user_id = payload.get("user_id") or payload.get("id")
    email = payload.get("email")

    logger.info(
        "auth.effect.user_registered",
        user_id=user_id,
        email=email,
    )

    try:
        from src.events.bus import Event, event_bus

        await event_bus.publish(
            Event(
                type="auth.user.registered.notify",
                data={
                    "user_id": user_id,
                    "email": email,
                },
                source="auth_store",
            )
        )
    except Exception as exc:
        logger.warning("auth.effect.notify_registration_failed", error=str(exc))


register_effects(
    auth_store,
    notify_login_effect,
    cleanup_session_effect,
    notify_status_change_effect,
    notify_registration_effect,
)
