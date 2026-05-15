"""Schema-level mutation tests for QARequest.tags field.

六鐵律 #2: test-adversary — written independently of implementation.

Killer invariants:
- tags=None vs tags=[] MUST be distinguishable ([] should NOT raise; None is default)
- tags=[1,2] MUST raise ValidationError (mutation: W2 might forget type coercion)
- tags="x" MUST raise (mutation: single string silently iterated as chars is a common bug)
- Existing fields (question/mode/top_k) must not be affected by tags addition
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.modules.docvault.schemas import QARequest


class TestQARequestTagsContract:
    """Verify QARequest.tags contract — new field must not break existing API."""

    def test_no_tags_field_defaults_to_none(self):
        """Not passing tags → req.tags is None (backward compat invariant)."""
        req = QARequest(question="what is foo?")
        assert req.tags is None, "Default must be None, not [] — breaks backward compat"

    def test_empty_list_accepted_no_validation_error(self):
        """tags=[] must be ACCEPTED (not raise). Killer: if impl treats [] same as None
        downstream, this is fine; but if Pydantic rejects it, that's a schema bug."""
        req = QARequest(question="q?", tags=[])
        assert req.tags == []  # explicitly [] — NOT None

    def test_empty_list_is_not_none(self):
        """[] vs None must be distinguishable at schema level.

        Mutation: if W2 accidentally wrote `tags: list[str] | None = []`,
        default would be [] and backward-compat breaks (callers testing `if not req.tags`
        would silently apply empty-list filter semantics).
        This is the most lethal invariant: empty-list default = silent regression.
        """
        req_no_tags = QARequest(question="q?")
        req_empty = QARequest(question="q?", tags=[])
        # They must differ at schema level
        assert req_no_tags.tags is None
        assert req_empty.tags == []
        assert req_no_tags.tags != req_empty.tags

    def test_string_list_accepted(self):
        """tags=["a","b"] → accepted, values preserved."""
        req = QARequest(question="q?", tags=["posts", "tech"])
        assert req.tags == ["posts", "tech"]

    def test_single_tag_accepted(self):
        """tags=["only-one"] → works."""
        req = QARequest(question="q?", tags=["only-one"])
        assert req.tags == ["only-one"]

    def test_int_list_raises_validation_error(self):
        """tags=[1,2] → ValidationError. Mutation: if W2 forgot type annotation."""
        with pytest.raises(ValidationError):
            QARequest(question="q?", tags=[1, 2])

    def test_string_not_list_raises_validation_error(self):
        """tags="just-a-string" → ValidationError.

        Killer: Python iterates strings as chars, so list("abc") == ["a","b","c"].
        If Pydantic coerces str→list[str], you get ["j","u","s","t",...] silently.
        This test ensures we get a hard error instead of silent char-explosion.
        """
        with pytest.raises(ValidationError):
            QARequest(question="q?", tags="just-a-string")

    def test_dict_not_accepted_as_tags(self):
        """tags={} → ValidationError."""
        with pytest.raises(ValidationError):
            QARequest(question="q?", tags={})

    def test_none_explicit_accepted(self):
        """tags=None (explicit) → same as default."""
        req = QARequest(question="q?", tags=None)
        assert req.tags is None


class TestQARequestExistingFieldsUnaffected:
    """Regression: adding tags must not disturb existing QARequest validation."""

    def test_question_min_length_still_enforced(self):
        with pytest.raises(ValidationError):
            QARequest(question="")

    def test_question_max_length_still_enforced(self):
        with pytest.raises(ValidationError):
            QARequest(question="x" * 2001)

    def test_mode_pattern_still_enforced(self):
        with pytest.raises(ValidationError):
            QARequest(question="q?", mode="invalid-mode")

    def test_top_k_lower_bound_still_enforced(self):
        with pytest.raises(ValidationError):
            QARequest(question="q?", top_k=0)

    def test_top_k_upper_bound_still_enforced(self):
        with pytest.raises(ValidationError):
            QARequest(question="q?", top_k=51)

    def test_full_valid_request_with_tags(self):
        """Combining all fields must work."""
        req = QARequest(
            question="what is docvault?",
            mode="factual",
            domain="docs",
            top_k=10,
            session_id="abc",
            tags=["posts", "2026"],
        )
        assert req.question == "what is docvault?"
        assert req.mode == "factual"
        assert req.top_k == 10
        assert req.tags == ["posts", "2026"]

    def test_full_valid_request_without_tags(self):
        """Existing callers with no tags field still work."""
        req = QARequest(
            question="what is docvault?",
            mode="mixed",
            top_k=5,
        )
        assert req.tags is None
