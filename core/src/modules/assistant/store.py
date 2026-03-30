"""Assistant state management — FeatureStore + NgRx patterns.

Tracks active conversations, streaming state, response latency stats,
and session health (tmux window availability).

Does NOT replicate DB — thin reactive layer on top of services.py.
PerformanceMiddleware is the primary middleware because AI response
latency is the critical observable for this module.
"""

from __future__ import annotations

import logging

from src.shared.actions import create_action, create_reducer, on
from src.shared.immutable_utils import batch_update, to_immutable, update_in
from src.shared.middleware import ErrorMiddleware, PerformanceMiddleware
from src.shared.selectors import create_selector
from src.shared.store import FeatureStore, effect

logger = logging.getLogger(__name__)

# ── 1. Actions ────────────────────────────────────────────────────────────

# Conversation lifecycle
ConversationStarted = create_action("assistant.conversation.started")
ConversationCompleted = create_action("assistant.conversation.completed")
ConversationFailed = create_action("assistant.conversation.failed")

# Message flow
MessageSent = create_action("assistant.message.sent")
ResponseStreaming = create_action("assistant.response.streaming")
ResponseGenerated = create_action("assistant.response.generated")

# Session health
SessionReady = create_action("assistant.session.ready")
SessionUnavailable = create_action("assistant.session.unavailable")

# ── 2. Reducer ────────────────────────────────────────────────────────────

_MAX_CONVERSATIONS = 100
_MAX_ERRORS = 20


def _handle_conversation_started(state, action):
    """Register new conversation in active_conversations and update totals."""
    payload = action.payload or {}
    conv_id = payload.get("conversation_id")
    if not conv_id:
        return state

    conv_entry = to_immutable(
        {
            "conversation_id": conv_id,
            "mode": payload.get("mode", "workshop"),
            "module": payload.get("module"),
            "started_at": payload.get("started_at"),
            "status": "streaming",
            "message_count": 0,
        }
    )
    active = state.get("active_conversations", {})
    return batch_update(
        state,
        {
            "active_conversations": active.set(conv_id, conv_entry),
            "total_conversations": state["total_conversations"] + 1,
            "last_activity_at": payload.get("started_at"),
        },
    )


def _handle_conversation_completed(state, action):
    """Move conversation from active to recent, accumulate response latency."""
    payload = action.payload or {}
    conv_id = payload.get("conversation_id")
    if not conv_id:
        return state

    active = state.get("active_conversations", {})
    conv = active.get(conv_id)

    new_active = active.delete(conv_id) if conv_id in active else active

    # Append to recent_conversations (capped)
    recent = state.get("recent_conversations", ())
    completed_entry = to_immutable(
        {
            "conversation_id": conv_id,
            "mode": conv.get("mode") if conv else payload.get("mode"),
            "response_ms": payload.get("response_ms"),
            "char_count": payload.get("char_count"),
            "completed_at": payload.get("completed_at"),
            "status": "completed",
        }
    )
    new_recent = (completed_entry, *recent)[:_MAX_CONVERSATIONS]

    # Accumulate response time for average calculation
    response_ms = payload.get("response_ms")
    total_ms = state["total_response_ms"]
    completed_count = state["completed_count"]
    if response_ms is not None:
        total_ms = total_ms + response_ms
        completed_count = completed_count + 1

    return batch_update(
        state,
        {
            "active_conversations": new_active,
            "recent_conversations": new_recent,
            "total_response_ms": total_ms,
            "completed_count": completed_count,
            "last_activity_at": payload.get("completed_at"),
        },
    )


def _handle_conversation_failed(state, action):
    """Remove conversation from active, append to recent_errors."""
    payload = action.payload or {}
    conv_id = payload.get("conversation_id")

    active = state.get("active_conversations", {})
    new_active = active.delete(conv_id) if conv_id and conv_id in active else active

    errors = state.get("recent_errors", ())
    error_entry = to_immutable(
        {
            "conversation_id": conv_id,
            "reason": payload.get("reason", "unknown"),
            "failed_at": payload.get("failed_at"),
        }
    )
    new_errors = (error_entry, *errors)[:_MAX_ERRORS]

    return batch_update(
        state,
        {
            "active_conversations": new_active,
            "recent_errors": new_errors,
            "failed_count": state["failed_count"] + 1,
            "last_activity_at": payload.get("failed_at"),
        },
    )


def _handle_message_sent(state, action):
    """Increment message_count for the active conversation."""
    payload = action.payload or {}
    conv_id = payload.get("conversation_id")
    if not conv_id:
        return state

    active = state.get("active_conversations", {})
    conv = active.get(conv_id)
    if conv is None:
        return state

    updated_conv = conv.set("message_count", conv.get("message_count", 0) + 1)
    return update_in(state, ["active_conversations"], lambda a: a.set(conv_id, updated_conv))


def _handle_response_streaming(state, action):
    """Update conversation status to streaming."""
    payload = action.payload or {}
    conv_id = payload.get("conversation_id")
    if not conv_id:
        return state

    active = state.get("active_conversations", {})
    conv = active.get(conv_id)
    if conv is None:
        return state

    updated_conv = conv.set("status", "streaming")
    return update_in(state, ["active_conversations"], lambda a: a.set(conv_id, updated_conv))


def _handle_session_ready(state, action):
    """Mark tmux assistant session as ready."""
    return batch_update(state, {"session_available": True})


def _handle_session_unavailable(state, action):
    """Mark tmux assistant session as unavailable."""
    payload = action.payload or {}
    return batch_update(
        state,
        {
            "session_available": False,
            "session_error": payload.get("reason", "unknown"),
        },
    )


assistant_reducer = create_reducer(
    {
        "active_conversations": {},
        "recent_conversations": [],
        "recent_errors": [],
        "total_conversations": 0,
        "completed_count": 0,
        "failed_count": 0,
        "total_response_ms": 0.0,
        "session_available": True,
        "session_error": None,
        "last_activity_at": None,
    },
    on(ConversationStarted, _handle_conversation_started),
    on(ConversationCompleted, _handle_conversation_completed),
    on(ConversationFailed, _handle_conversation_failed),
    on(MessageSent, _handle_message_sent),
    on(ResponseStreaming, _handle_response_streaming),
    on(ResponseGenerated, lambda s, a: s),
    on(SessionReady, _handle_session_ready),
    on(SessionUnavailable, _handle_session_unavailable),
)

# ── 3. Selectors ─────────────────────────────────────────────────────────

select_active_conversations = create_selector(lambda s: s["active_conversations"])
select_recent_conversations = create_selector(lambda s: s["recent_conversations"])
select_recent_errors = create_selector(lambda s: s["recent_errors"])
select_session_available = create_selector(lambda s: s["session_available"])
select_completed_count = create_selector(lambda s: s["completed_count"])
select_failed_count = create_selector(lambda s: s["failed_count"])
select_total_response_ms = create_selector(lambda s: s["total_response_ms"])

select_avg_response_ms = create_selector(
    select_total_response_ms,
    select_completed_count,
    result_fn=lambda total_ms, count: round(total_ms / count, 1) if count > 0 else 0.0,
)

select_active_count = create_selector(
    select_active_conversations,
    result_fn=lambda active: len(active) if active else 0,
)

select_last_error = create_selector(
    select_recent_errors,
    result_fn=lambda errors: errors[0] if errors else None,
)

select_success_rate = create_selector(
    select_completed_count,
    select_failed_count,
    result_fn=lambda completed, failed: (
        round(completed / (completed + failed), 3) if (completed + failed) > 0 else 1.0
    ),
)

# ── 4. Store (with PerformanceMiddleware) ──────────────────────────────────

# AI response latency is the key metric — threshold 2000ms (slower than typical actions)
_perf_mw = PerformanceMiddleware(warn_threshold_ms=2000.0)
_error_mw = ErrorMiddleware()

assistant_store: FeatureStore = FeatureStore(
    "assistant",
    assistant_reducer,
    middlewares=[_perf_mw, _error_mw],
)

# ── 5. Effects ────────────────────────────────────────────────────────────


@effect(ConversationCompleted, store=assistant_store)
async def log_response_latency(action, store):
    """Log response latency for observability (structured log for LGTM)."""
    payload = action.payload or {}
    response_ms = payload.get("response_ms")
    conv_id = payload.get("conversation_id", "?")
    mode = payload.get("mode", "?")
    char_count = payload.get("char_count", 0)

    if response_ms is not None:
        logger.info(
            "assistant.response.latency conv_id=%s mode=%s response_ms=%.1f chars=%d",
            conv_id,
            mode,
            response_ms,
            char_count or 0,
        )

        # Escalate to warning if response exceeds 30s
        if response_ms > 30_000:
            logger.warning(
                "assistant: slow response detected conv_id=%s response_ms=%.1f",
                conv_id,
                response_ms,
            )


@effect(ConversationFailed, store=assistant_store)
async def notify_session_failure(action, store):
    """Detect session failures and dispatch SessionUnavailable to update health state."""
    payload = action.payload or {}
    reason = payload.get("reason", "")

    if "tmux" in reason.lower() or "session" in reason.lower():
        logger.warning("assistant: session-related failure detected reason=%s", reason)
        await store.dispatch(SessionUnavailable(reason=reason))


# ── 6. Public helpers ──────────────────────────────────────────────────────


def get_perf_stats() -> dict:
    """Get PerformanceMiddleware stats (action type -> count/avg/max/p95)."""
    return _perf_mw.get_stats()
