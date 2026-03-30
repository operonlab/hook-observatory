"""Voice Gateway — FeatureStore (FULL depth).

Models the voice FSM (IDLE → LISTENING → PROCESSING → RESPONDING) as
immutable state. Wires StateTransitioned, audio/STT events, and session
lifecycle actions through a PerformanceMiddleware-instrumented store.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

from src.shared.actions import create_action, create_reducer, on
from src.shared.immutable_utils import batch_update, to_immutable
from src.shared.middleware import PerformanceMiddleware
from src.shared.selectors import create_selector
from src.shared.store import FeatureStore, effect, register_effects

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

# ── Store ─────────────────────────────────────────────────────────────────────

voice_store = FeatureStore(
    "voice-gateway",
    voice_reducer,
    middlewares=[PerformanceMiddleware(warn_threshold_ms=500.0)],
)

# ── Effects ───────────────────────────────────────────────────────────────────


@effect(VoiceSessionEnded, store=voice_store)
async def log_session_duration(action, store) -> None:
    """Log session duration when a voice session ends."""
    state = store.get_state()
    transitions = state.get("transitions", 0)
    chunks = state.get("chunks_processed", 0)
    logger.info(
        "voice_session_ended",
        extra={
            "transitions": transitions,
            "chunks_processed": chunks,
        },
    )


@effect(STTResultReceived, store=voice_store)
async def log_transcription(action, store) -> None:
    """Log STT transcription result for observability."""
    p = action.payload or {}
    text = p.get("text", "") if isinstance(p, dict) else ""
    language = p.get("language", "") if isinstance(p, dict) else ""
    engine = p.get("engine", "") if isinstance(p, dict) else ""
    latency_ms = p.get("latency_ms", 0) if isinstance(p, dict) else 0
    logger.info(
        "voice_stt_result",
        extra={
            "text_length": len(text),
            "language": language,
            "engine": engine,
            "latency_ms": latency_ms,
        },
    )


@effect(CommandRecognized, store=voice_store)
async def log_command(action, store) -> None:
    """Log recognized command for audit trail."""
    p = action.payload or {}
    command = p.get("command", "") if isinstance(p, dict) else ""
    confidence = p.get("confidence", 0.0) if isinstance(p, dict) else 0.0
    state = store.get_state()
    count = state.get("commands_recognized", 0)
    logger.info(
        "voice_command_recognized",
        extra={
            "command": command,
            "confidence": confidence,
            "total_commands": count,
        },
    )


register_effects(
    voice_store,
    log_session_duration,
    log_transcription,
    log_command,
)
