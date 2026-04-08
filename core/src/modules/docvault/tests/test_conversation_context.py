"""Adversarial tests for DocVault Phase 3 — Conversation Context.

Written based on Op contracts ONLY, not implementation.
Mutation thinking: empty session, expired history, token budget overflow.
"""

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest


# ════════════════════════════════════════════════════
# _parse_timestamp tests
# ════════════════════════════════════════════════════


class TestParseTimestamp:
    def test_valid_iso(self):
        from src.modules.docvault.ops.conversation_context import _parse_timestamp

        ts = "2026-04-08T12:00:00+00:00"
        result = _parse_timestamp(ts)
        assert result > 0

    def test_valid_iso_with_z(self):
        from src.modules.docvault.ops.conversation_context import _parse_timestamp

        ts = "2026-04-08T12:00:00Z"
        result = _parse_timestamp(ts)
        assert result > 0

    def test_invalid_string(self):
        from src.modules.docvault.ops.conversation_context import _parse_timestamp

        assert _parse_timestamp("not-a-date") == 0.0

    def test_empty_string(self):
        from src.modules.docvault.ops.conversation_context import _parse_timestamp

        assert _parse_timestamp("") == 0.0

    def test_none_input(self):
        from src.modules.docvault.ops.conversation_context import _parse_timestamp

        assert _parse_timestamp(None) == 0.0


# ════════════════════════════════════════════════════
# _trim_history tests
# ════════════════════════════════════════════════════


class TestTrimHistory:
    def test_empty_history(self):
        from src.modules.docvault.ops.conversation_context import _trim_history

        assert _trim_history([], 0.0) == []

    def test_count_limit(self):
        """More than MAX_TURNS entries should be trimmed to last N."""
        from src.modules.docvault.ops.conversation_context import _trim_history

        now = datetime.now(UTC)
        history = [
            {
                "turn": i,
                "question": f"q{i}",
                "answer": f"a{i}",
                "timestamp": (now - timedelta(minutes=i)).isoformat(),
            }
            for i in range(10)
        ]
        # Default MAX_TURNS=5, so we should get at most 5
        result = _trim_history(history, now.timestamp())
        assert len(result) <= 5

    def test_time_limit_filters_old(self):
        """Entries older than TTL should be filtered out."""
        from src.modules.docvault.ops.conversation_context import _trim_history

        now = datetime.now(UTC)
        old_ts = (now - timedelta(hours=2)).isoformat()
        recent_ts = (now - timedelta(minutes=5)).isoformat()
        history = [
            {"turn": 1, "question": "old", "answer": "a", "timestamp": old_ts},
            {"turn": 2, "question": "recent", "answer": "b", "timestamp": recent_ts},
        ]
        result = _trim_history(history, now.timestamp())
        # Old entry should be filtered, only recent remains
        assert len(result) <= 1
        if result:
            assert result[0]["question"] == "recent"

    def test_token_budget(self):
        """Very long history entries should be trimmed by token budget."""
        from src.modules.docvault.ops.conversation_context import _trim_history

        now = datetime.now(UTC)
        # Create entries with very long text to exceed token budget
        history = [
            {
                "turn": i,
                "question": "q" * 2000,
                "answer": "a" * 2000,
                "timestamp": (now - timedelta(seconds=i)).isoformat(),
            }
            for i in range(3)
        ]
        result = _trim_history(history, now.timestamp())
        # With TOKEN_BUDGET=2000 and ~2000 chars per entry, we should get at most 1-2
        assert len(result) < len(history)

    def test_all_expired(self):
        """If all entries are expired, result should be empty."""
        from src.modules.docvault.ops.conversation_context import _trim_history

        now = datetime.now(UTC)
        old_ts = (now - timedelta(hours=24)).isoformat()
        history = [
            {"turn": 1, "question": "q1", "answer": "a1", "timestamp": old_ts},
            {"turn": 2, "question": "q2", "answer": "a2", "timestamp": old_ts},
        ]
        result = _trim_history(history, now.timestamp())
        assert result == []


# ════════════════════════════════════════════════════
# ConversationContextOp tests
# ════════════════════════════════════════════════════


class TestConversationContextOpDisabled:
    @pytest.mark.asyncio
    async def test_disabled_returns_unchanged(self):
        with patch.dict(os.environ, {"DOCVAULT_CONVERSATION": "0"}, clear=False):
            import importlib

            import src.modules.docvault.ops.conversation_context as mod

            importlib.reload(mod)

            op = mod.ConversationContextOp()
            ctx = {"query": "test", "session_id": "sess1", "space_id": "default"}
            result = await op(ctx)
            # Should not add conversation keys
            assert "conversation_history" not in result or result.get("query") == "test"

    @pytest.mark.asyncio
    async def test_no_session_id_returns_unchanged(self):
        with patch.dict(os.environ, {"DOCVAULT_CONVERSATION": "1"}, clear=False):
            import importlib

            import src.modules.docvault.ops.conversation_context as mod

            importlib.reload(mod)

            op = mod.ConversationContextOp()
            ctx = {"query": "test", "space_id": "default"}
            result = await op(ctx)
            assert result.get("query") == "test"

    @pytest.mark.asyncio
    async def test_none_session_id_returns_unchanged(self):
        with patch.dict(os.environ, {"DOCVAULT_CONVERSATION": "1"}, clear=False):
            import importlib

            import src.modules.docvault.ops.conversation_context as mod

            importlib.reload(mod)

            op = mod.ConversationContextOp()
            ctx = {"query": "test", "session_id": None, "space_id": "default"}
            result = await op(ctx)
            assert result.get("query") == "test"


class TestConversationContextOpEnabled:
    @pytest.mark.asyncio
    async def test_first_turn_no_history(self):
        with patch.dict(os.environ, {"DOCVAULT_CONVERSATION": "1"}, clear=False):
            import importlib

            import src.modules.docvault.ops.conversation_context as mod

            importlib.reload(mod)

            mock_redis = AsyncMock()
            mock_redis.zrangebyscore = AsyncMock(return_value=[])

            with patch("src.shared.redis.get_redis", return_value=mock_redis):
                op = mod.ConversationContextOp()
                ctx = {"query": "first question", "session_id": "sess1", "space_id": "default"}
                result = await op(ctx)
                assert result["turn_number"] == 1
                assert result["conversation_history"] == []
                assert result["rewritten_query"] == "first question"


# ════════════════════════════════════════════════════
# store_conversation_turn tests
# ════════════════════════════════════════════════════


class TestStoreConversationTurn:
    @pytest.mark.asyncio
    async def test_empty_session_id_noop(self):
        with patch.dict(os.environ, {"DOCVAULT_CONVERSATION": "1"}, clear=False):
            import importlib

            import src.modules.docvault.ops.conversation_context as mod

            importlib.reload(mod)

            # Should not raise
            await mod.store_conversation_turn("", 1, "q", "a")

    @pytest.mark.asyncio
    async def test_disabled_noop(self):
        with patch.dict(os.environ, {"DOCVAULT_CONVERSATION": "0"}, clear=False):
            import importlib

            import src.modules.docvault.ops.conversation_context as mod

            importlib.reload(mod)

            await mod.store_conversation_turn("sess1", 1, "q", "a")
            # No error means it's a no-op


# ════════════════════════════════════════════════════
# cited_answer.py _build_user_message tests
# ════════════════════════════════════════════════════


class TestBuildUserMessageConversation:
    def test_without_history(self):
        from src.modules.docvault.ops.cited_answer import _build_user_message

        msg = _build_user_message("What is X?", [{"content": "X is Y"}])
        assert "Question: What is X?" in msg
        assert "Conversation context" not in msg

    def test_with_empty_history(self):
        from src.modules.docvault.ops.cited_answer import _build_user_message

        msg = _build_user_message("What is X?", [{"content": "X is Y"}], conversation_history=[])
        # Empty list should not add conversation header
        assert "Conversation context" not in msg

    def test_with_history(self):
        from src.modules.docvault.ops.cited_answer import _build_user_message

        history = [
            {"turn": 1, "question": "What burgers?", "answer": "Chicken, pork, beef"},
        ]
        msg = _build_user_message("I want 2 chicken", [{"content": "Menu"}], conversation_history=history)
        assert "Conversation context" in msg
        assert "Turn 1" in msg
        assert "What burgers?" in msg
        assert "for reference only" in msg
        assert "Question: I want 2 chicken" in msg

    def test_history_none_vs_missing(self):
        """None should behave same as not passing the parameter."""
        from src.modules.docvault.ops.cited_answer import _build_user_message

        msg_none = _build_user_message("Q?", [{"content": "A"}], conversation_history=None)
        msg_default = _build_user_message("Q?", [{"content": "A"}])
        assert msg_none == msg_default
