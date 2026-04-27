"""Adversary tests for compute_content_hash.

Mutation thinking targets:
- author calls .lower() -> case-insensitivity (design says hash, not normalize-case)
- author skips whitespace collapse -> "a b" != "a  b" breaks idempotency
- author NFC-normalizes -> Unicode equivalent forms collide (probably wanted)
- author crashes on None instead of empty-string fallback (docstring implies fallback)
"""

import pytest

from src.modules.memvault.fold_verifier import compute_content_hash


def test_content_hash_whitespace_collapsed_idempotent():
    """Mutation: drop split()/join collapse -> these would diverge."""
    a = compute_content_hash("hello world")
    b = compute_content_hash("hello   world")
    c = compute_content_hash("  hello\tworld\n")
    d = compute_content_hash("hello\n\nworld")
    assert a == b == c == d


def test_content_hash_case_sensitive():
    """Mutation: author silently calls .lower() -> these would collide.

    Design intent: content_hash detects child-content drift. Capitalization
    IS drift (e.g., 'iPhone' vs 'iphone' may matter for entity extraction).
    """
    a = compute_content_hash("Alfred is a butler.")
    b = compute_content_hash("alfred is a butler.")
    A = compute_content_hash("ALFRED IS A BUTLER.")
    assert a != b, "compute_content_hash appears to lower-case; should be case-sensitive"
    assert a != A
    assert b != A


def test_content_hash_unicode_nfc_vs_nfd_currently_distinct():
    """e + combining-acute vs precomposed é.

    sha256 over raw UTF-8 will treat them as different. Author may
    intentionally normalize (NFC) — if so, this test fails and is a signal
    to document the choice. We assert the byte-level behavior because it's
    the simpler / least-surprising default.
    """
    nfc = "café"  # precomposed
    nfd = "café"  # e + combining acute
    assert nfc != nfd  # precondition
    h_nfc = compute_content_hash(nfc)
    h_nfd = compute_content_hash(nfd)
    # If author silently NFC-normalizes, these will be equal — surface that.
    assert h_nfc != h_nfd, (
        "compute_content_hash silently normalizes Unicode; document this in design"
    )


def test_content_hash_empty_string_is_stable_sentinel():
    """Empty + whitespace-only must collapse to same hash, not crash."""
    a = compute_content_hash("")
    b = compute_content_hash("   ")
    c = compute_content_hash("\n\t  ")
    assert a == b == c
    assert isinstance(a, str)
    assert len(a) == 16


def test_content_hash_none_is_handled_via_or_fallback():
    """The implementation uses ``(text or '').split()`` per design; None is
    treated as empty rather than raising. Mutation: drop the ``or ''`` and
    None will TypeError on .split().
    """
    # Should NOT raise — None falls back to empty per ``(text or '')``.
    out = compute_content_hash(None)  # type: ignore[arg-type]
    assert out == compute_content_hash("")


def test_content_hash_returns_16_hex():
    out = compute_content_hash("anything")
    assert isinstance(out, str)
    assert len(out) == 16
    int(out, 16)


def test_content_hash_drift_detection():
    """Different content -> different hash. The whole point of this fn."""
    assert compute_content_hash("v1 of fold") != compute_content_hash("v2 of fold")
    assert compute_content_hash("Alfred") != compute_content_hash("JARVIS")
