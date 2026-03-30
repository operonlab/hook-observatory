"""Voice Gateway — FeatureStore (FULL depth).

Models the voice FSM (IDLE → LISTENING → PROCESSING → RESPONDING) as
immutable state. Wires StateTransitioned, audio/STT events, and session
lifecycle actions through a PerformanceMiddleware-instrumented store.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

from src.shared.actions import Action, create_action, create_reducer, on
from src.shared.immutable_utils import batch_update, to_immutable
from src.shared.selectors import create_selector
from src.shared.store import FeatureStore

logger = logging.getLogger(__name__)

# ── Actions ──────────────────────────────────────────────────────────────────

VoiceSessionStarted = create_action("voice.session.started")
VoiceSessionEnded = create_action("voice.session.ended")
StateTransitioned = create_action("voice.state.transitioned")
AudioChunkProcessed = create_action("voice.audio.processed")
WakeWordDetected = create_action("voice.wakeword.detected")
STTResultReceived = create_action("voice.stt.result_received")
CommandRecognized = create_action("voice.command.recognized")

# ── Reducer ──────────────────────────────────────────────────────────────────

_INITIAL_STATE = {
    "state": "idle",  # idle | listening | processing | responding
    "active_session": None,
    "chunks_processed": 0,
    "commands_recognized": 0,
    "last_stt_result": None,
    "wakeword_count": 0,
    "transitions": 0,
}

voice_reducer = create_reducer(
    _INITIAL_STATE,
    on(
        VoiceSessionStarted,
        lambda s, a: batch_update(
            s,
            {
                "state": "listening",
                "active_session": to_immutable(a.payload or {}),
            },
        ),
    ),
    on(
        StateTransitioned,
        lambda s, a: batch_update(
            s,
            {
                "state": (a.payload or {}).get("to_state", "idle"),
                "transitions": s["transitions"] + 1,
            },
        ),
    ),
    on(
        AudioChunkProcessed,
        lambda s, a: s.set("chunks_processed", s["chunks_processed"] + 1),
    ),
    on(
        STTResultReceived,
        lambda s, a: s.set("last_stt_result", to_immutable(a.payload or {})),
    ),
    on(
        WakeWordDetected,
        lambda s, a: s.set("wakeword_count", s["wakeword_count"] + 1),
    ),
    on(
        CommandRecognized,
        lambda s, a: s.set("commands_recognized", s["commands_recognized"] + 1),
    ),
    on(
        VoiceSessionEnded,
        lambda s, a: batch_update(
            s,
            {
                "state": "idle",
                "active_session": None,
            },
        ),
    ),
)

# ── Selectors ─────────────────────────────────────────────────────────────────

select_voice_state = create_selector(lambda s: s["state"])
select_active_session = create_selector(lambda s: s["active_session"])
select_chunks_processed = create_selector(lambda s: s["chunks_processed"])
select_commands_recognized = create_selector(lambda s: s["commands_recognized"])
select_last_stt_result = create_selector(lambda s: s["last_stt_result"])
select_wakeword_count = create_selector(lambda s: s["wakeword_count"])

select_is_active = create_selector(
    lambda s: s["state"],
    result_fn=lambda state: state != "idle",
)

select_pipeline_summary = create_selector(
    lambda s: s["state"],
    lambda s: s["chunks_processed"],
    lambda s: s["transitions"],
    result_fn=lambda state, chunks, transitions: {
        "state": state,
        "chunks_processed": chunks,
        "transitions": transitions,
    },
)

# ── Performance Middleware ────────────────────────────────────────────────────


class PerformanceMiddleware:
    """Log dispatch latency for each action through the voice store."""

    async def before_dispatch(self, action: Action, state) -> Action:
        action._ts_start = time.perf_counter()  # type: ignore[attr-defined]
        return action

    async def after_dispatch(self, action: Action, old_state, new_state) -> None:
        ts_start = getattr(action, "_ts_start", None)
        if ts_start is not None:
            elapsed_ms = (time.perf_counter() - ts_start) * 1000
            logger.debug("voice_store dispatch: type=%s latency=%.2fms", action.type, elapsed_ms)

    async def on_error(self, action: Action, state, exc: Exception) -> None:
        logger.error("voice_store error: type=%s error=%s", action.type, exc)


# ── Store ─────────────────────────────────────────────────────────────────────

voice_store = FeatureStore(
    "voice-gateway",
    voice_reducer,
    middlewares=[PerformanceMiddleware()],
)
