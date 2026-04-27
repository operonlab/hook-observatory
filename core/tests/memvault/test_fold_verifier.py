"""Worker 2 unit tests — pure-function coverage of fold_verifier."""

import asyncio

from src.modules.memvault.fold_verifier import (
    compute_content_hash,
    compute_fold_id,
    verify_fold_extractiveness,
)


def test_fold_id_idempotent_same_children_same_content():
    children = ["b1", "b2", "b3"]
    text = "Alfred is a butler. JARVIS is an AI."
    assert compute_fold_id(children) == compute_fold_id(list(reversed(children)))
    assert compute_content_hash(text) == compute_content_hash(text)


def test_fold_id_changes_on_content_drift():
    children = ["b1", "b2"]
    assert compute_fold_id(children) == compute_fold_id(children)
    assert compute_content_hash("v1 of the fold") != compute_content_hash("v2 of the fold")


def test_verifier_rejects_ungrounded_sentence():
    children_texts = ["Alfred is a butler.", "JARVIS is an AI."]
    fold_text = "Alfred is a butler. The moon is made of cheese."
    result = asyncio.run(
        verify_fold_extractiveness(fold_text, children_texts, use_embedding=False)
    )
    assert "Alfred is a butler." in result.accepted
    assert any("moon" in s for s in result.rejected)
