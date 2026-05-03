"""Unit test — auto_evolve_kg content hashing + idempotency contract.

Pure unit test: only exercises the _content_hash helper and the import path
of KGAutoEvolveLog (smoke that the model class is wired). Full end-to-end
needs a real DB and is left to integration tests.
"""

from __future__ import annotations

import os
import sys

# Path fixup
_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKTREE_CORE = os.path.normpath(os.path.join(_HERE, "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(_WORKTREE_CORE, "src"))
sys.path.insert(0, _WORKTREE_CORE)
for libname in ("text-ops", "kg-ops", "sdk-client", "tmux-lib"):
    p = f"/Users/joneshong/workshop/libs/{libname}"
    if p not in sys.path:
        sys.path.insert(0, p)


def test_content_hash_stable_across_whitespace_changes():
    from src.modules.memvault.kg_auto_evolve import _content_hash

    # Same prose, varied whitespace → same hash (so trivial reformatting
    # short-circuits idempotency).
    h1 = _content_hash("hello world")
    h2 = _content_hash("hello   world")
    h3 = _content_hash("hello\nworld")
    h4 = _content_hash("  hello world  ")
    assert h1 == h2 == h3 == h4


def test_content_hash_changes_with_actual_edit():
    from src.modules.memvault.kg_auto_evolve import _content_hash

    h1 = _content_hash("hello world")
    h2 = _content_hash("hello WORLD")  # case change matters
    h3 = _content_hash("hello world!")  # punctuation change matters
    assert h1 != h2
    assert h1 != h3


def test_content_hash_is_sha256_hex():
    from src.modules.memvault.kg_auto_evolve import _content_hash

    h = _content_hash("anything")
    assert len(h) == 64  # SHA256 hex
    int(h, 16)  # must be valid hex


def test_kg_auto_evolve_log_model_importable():
    from src.modules.memvault.kg_models import KGAutoEvolveLog

    assert KGAutoEvolveLog.__tablename__ == "kg_auto_evolve_log"
    cols = {c.name for c in KGAutoEvolveLog.__table__.columns}
    assert {"memory_id", "content_hash", "triples_extracted", "triples_stored"} <= cols


if __name__ == "__main__":
    test_content_hash_stable_across_whitespace_changes()
    test_content_hash_changes_with_actual_edit()
    test_content_hash_is_sha256_hex()
    test_kg_auto_evolve_log_model_importable()
    print("ok 4/4")
