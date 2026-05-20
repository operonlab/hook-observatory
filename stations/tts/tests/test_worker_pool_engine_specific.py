"""worker_pool.synth flattens engine_specific into the worker payload.

The keep-alive worker daemons dispatch via _do_synth(**cmd) — so any
engine_specific keys (emotion, instruct, seed, ...) must reach the worker
as top-level keys, not nested under "engine_specific".

# MUTATION TARGETS
# 1. engine_specific keys flatten into the payload (not nested)
# 2. ref_text inside engine_specific only wins when positional is absent
# 3. None / missing engine_specific is a no-op
# 4. synth_batch applies the same rule per item
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

TTS_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def wp_mod():
    # Keep stations/tts on sys.path for the lifetime of the fixture — dataclass
    # introspection inside worker_pool reaches into sys.modules at field
    # resolution time, so removing the entry early breaks it.
    if str(TTS_ROOT) not in sys.path:
        sys.path.insert(0, str(TTS_ROOT))
    import worker_pool as mod  # type: ignore[import-not-found]
    return mod


def _build_pool(wp_mod):
    """Construct a WorkerPool with mocked workers + bypass _ensure_active."""
    pool = wp_mod.WorkerPool.__new__(wp_mod.WorkerPool)
    pool._lock = asyncio.Lock()
    pool.last_used = 0.0
    pool.workers = {}
    pool.active_engine = None
    pool.active_worker_id = None

    fake_worker = MagicMock()
    fake_worker.send = AsyncMock(return_value={"ok": True, "audio_b64": "", "sample_rate": 24000})
    pool._fake_worker = fake_worker

    async def _ensure(name):
        return fake_worker

    pool._ensure_active = _ensure
    return pool


def test_synth_flattens_engine_specific(wp_mod):
    pool = _build_pool(wp_mod)
    asyncio.run(
        pool.synth(
            engine_name="indextts2_base",
            text="hi",
            lang="zh",
            voice_id="master",
            engine_specific={"emotion": {"preset": "happy"}, "instruct": "joyful"},
        )
    )
    sent = pool._fake_worker.send.call_args[0][0]
    assert sent["op"] == "synth"
    assert sent["emotion"] == {"preset": "happy"}
    assert sent["instruct"] == "joyful"
    # Not nested under engine_specific
    assert "engine_specific" not in sent


def test_synth_engine_specific_ref_text_filled_when_positional_empty(wp_mod):
    pool = _build_pool(wp_mod)
    asyncio.run(
        pool.synth(
            engine_name="cosyvoice_v3_native",
            text="hi",
            lang="zh",
            ref_text=None,
            engine_specific={"ref_text": "from_es"},
        )
    )
    sent = pool._fake_worker.send.call_args[0][0]
    assert sent["ref_text"] == "from_es"


def test_synth_positional_ref_text_wins(wp_mod):
    pool = _build_pool(wp_mod)
    asyncio.run(
        pool.synth(
            engine_name="cosyvoice_v3_native",
            text="hi",
            lang="zh",
            ref_text="from_positional",
            engine_specific={"ref_text": "from_es"},
        )
    )
    sent = pool._fake_worker.send.call_args[0][0]
    assert sent["ref_text"] == "from_positional"


def test_synth_no_engine_specific_is_noop(wp_mod):
    pool = _build_pool(wp_mod)
    asyncio.run(pool.synth(engine_name="x", text="hi", lang="zh"))
    sent = pool._fake_worker.send.call_args[0][0]
    assert sent["ref_text"] == ""
    # No spurious extras beyond the documented op fields
    assert set(sent) == {"op", "text", "lang", "voice_id", "speed", "ref_text"}


def test_synth_batch_per_item_engine_specific(wp_mod):
    pool = _build_pool(wp_mod)
    items = [
        {"text": "a", "lang": "zh", "engine_specific": {"emotion": {"preset": "happy"}}},
        {"text": "b", "lang": "zh", "engine_specific": {"instruct": "softly"}},
    ]
    asyncio.run(pool.synth_batch("indextts2_base", items))
    calls = pool._fake_worker.send.call_args_list
    assert len(calls) == 2
    assert calls[0][0][0]["emotion"] == {"preset": "happy"}
    assert "instruct" not in calls[0][0][0]
    assert calls[1][0][0]["instruct"] == "softly"
    assert "emotion" not in calls[1][0][0]
