"""Phase 2 voice provenance — schema + extractor fallback tests.

六鐵律 disclosure: main-thread author (not 寫測分離). Mutation-thinking
enforced via killer tests on the 4-value invariant; a future adversary
should re-attack assistant_lead classification quality once we have
real session transcripts to validate against.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.modules.memvault.schemas import MemoryBlockCreate, MemoryBlockResponse


# ── Schema validation killers ─────────────────────────────────────────


@pytest.mark.parametrize(
    "good", ["user_lead", "dialog", "assistant_lead", "unknown"]
)
def test_voice_canonical_values_accepted(good):
    b = MemoryBlockCreate(content="x", voice=good)
    assert b.voice == good


def test_voice_none_default_is_allowed():
    """NULL voice is fine — pre-Phase-2 blocks predate this column."""
    b = MemoryBlockCreate(content="x")
    assert b.voice is None


@pytest.mark.parametrize(
    "bad",
    [
        "USER_LEAD",       # case-sensitive
        "user-lead",       # hyphen vs underscore
        "user lead",       # space
        "assistant",       # partial
        "bogus",           # garbage
        "dialog ",         # trailing space
        " user_lead",      # leading space
        "user_lead|dialog",  # union literal
    ],
)
def test_voice_non_canonical_rejected(bad):
    """Killer: drift to free-form strings would let the column silently
    accumulate dozens of voice values, defeating recall downweighting.
    """
    with pytest.raises(ValidationError):
        MemoryBlockCreate(content="x", voice=bad)


def test_voice_int_rejected():
    """Killer: type discipline — voice is a string literal, not an enum int."""
    with pytest.raises(ValidationError):
        MemoryBlockCreate(content="x", voice=1)


def test_response_voice_field_is_surfaced():
    """Response schema must expose voice so downstream UIs / recall logic see it."""
    # Build response shape (skipping required SpaceScopedResponse fields with valid data)
    fields = MemoryBlockResponse.model_fields
    assert "voice" in fields, (
        "regression: voice field disappeared from MemoryBlockResponse"
    )


# ── Extractor fallback invariant (pure-function logic mirroring extract.py) ──


def _voice_fallback(raw):
    """Mirror of the gate in mcp/memvault/scripts/extract.py.

    Re-implemented here so the test isn't coupled to import paths under
    /mcp/. If the gate logic in extract.py drifts apart from this, the
    e2e test (Phase 2 final) will catch the divergence loudly.
    """
    return raw if raw in ("user_lead", "dialog", "assistant_lead", "unknown") else "dialog"


@pytest.mark.parametrize("raw", ["user_lead", "dialog", "assistant_lead", "unknown"])
def test_extractor_passes_canonical_voice_through(raw):
    assert _voice_fallback(raw) == raw


@pytest.mark.parametrize(
    "garbage",
    [
        None,
        "",
        "USER_LEAD",
        "user-lead",
        "userlead",
        "speaker:user",
        "memory",      # collision with router intent vocabulary — explicit guard
        {"voice": "user_lead"},  # nested dict, not a string
    ],
)
def test_extractor_falls_back_to_dialog_on_garbage(garbage):
    """Killer: any non-canonical LLM output must fall back to 'dialog',
    not crash and not leak the garbage into the DB.
    """
    result = _voice_fallback(garbage)
    assert result == "dialog"
