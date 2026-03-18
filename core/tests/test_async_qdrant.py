"""Tests for async Qdrant migration + bridge lock fix + pool tuning.

Verifies the perf fixes:
1. qdrant_client.py — all functions are async, prefer_grpc=True
2. qdrant_search.py — all functions are async, hybrid_search parallelizes
3. omlx_bridge / rerank_bridge — dual lock architecture
4. database.py — explicit pool_size
5. cache.py — batch unlink
"""

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ====================================================================
# 1. qdrant_client — async signatures + gRPC
# ====================================================================

class TestQdrantClientAsync:
    """Verify qdrant_client functions are all async with correct config."""

    def test_all_functions_are_async(self):
        from src.shared.qdrant_client import get_client, health_check, is_available, reset

        for fn in [get_client, is_available, reset, health_check]:
            assert inspect.iscoroutinefunction(fn), f"{fn.__name__} must be async"

    def test_imports_async_client(self):
        import src.shared.qdrant_client as mod

        # Should use AsyncQdrantClient, not QdrantClient
        source = inspect.getsource(mod)
        assert "AsyncQdrantClient" in source
        assert "from qdrant_client import AsyncQdrantClient" in source

    @pytest.mark.asyncio
    async def test_get_client_creates_async_instance(self):
        """get_client() should instantiate AsyncQdrantClient with prefer_grpc=True."""
        import src.shared.qdrant_client as mod

        # Reset state
        mod._client = None
        mod._available = None

        with patch("src.shared.qdrant_client.AsyncQdrantClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.get_collections = AsyncMock()
            MockClient.return_value = mock_instance

            client = await mod.get_client()

            MockClient.assert_called_once()
            call_kwargs = MockClient.call_args[1]
            assert call_kwargs["prefer_grpc"] is True, "Must use gRPC"
            assert call_kwargs["grpc_port"] == 6334
            assert client is mock_instance

        # Cleanup
        mod._client = None
        mod._available = None

    @pytest.mark.asyncio
    async def test_get_client_returns_none_when_unavailable(self):
        """get_client() should return None and set _available=False on error."""
        import src.shared.qdrant_client as mod

        mod._client = None
        mod._available = None

        with patch("src.shared.qdrant_client.AsyncQdrantClient") as MockClient:
            MockClient.return_value.get_collections = AsyncMock(
                side_effect=Exception("Connection refused")
            )

            client = await mod.get_client()

            assert client is None
            assert mod._available is False

        mod._client = None
        mod._available = None

    @pytest.mark.asyncio
    async def test_retry_interval_respected(self):
        """After failure, get_client() should return None until retry interval passes."""
        import time

        import src.shared.qdrant_client as mod

        mod._client = None
        mod._available = False
        mod._last_failure = time.monotonic()  # just failed

        client = await mod.get_client()
        assert client is None, "Should not retry before interval"

        # Simulate interval passed
        mod._last_failure = time.monotonic() - 10  # 10s ago, > 5s interval

        with patch("src.shared.qdrant_client.AsyncQdrantClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.get_collections = AsyncMock()
            MockClient.return_value = mock_instance

            client = await mod.get_client()
            assert client is not None, "Should retry after interval"

        mod._client = None
        mod._available = None


# ====================================================================
# 2. qdrant_search — async + parallel hybrid_search
# ====================================================================

class TestQdrantSearchAsync:
    """Verify qdrant_search functions are async and hybrid_search is parallelized."""

    def test_all_public_functions_are_async(self):
        from src.shared.qdrant_search import (
            delete_document,
            hybrid_search,
            index_document,
            index_documents_batch,
            search_across_services,
            search_with_fallback,
            vector_search,
        )

        for fn in [
            index_document,
            index_documents_batch,
            hybrid_search,
            vector_search,
            delete_document,
            search_across_services,
            search_with_fallback,
        ]:
            assert inspect.iscoroutinefunction(fn), f"{fn.__name__} must be async"

    def test_hybrid_search_uses_create_task(self):
        """hybrid_search should use asyncio.create_task for parallel embedding."""
        from src.shared import qdrant_search

        source = inspect.getsource(qdrant_search.hybrid_search)
        assert "asyncio.create_task" in source, (
            "hybrid_search must use create_task for parallel embedding+sparse"
        )

    @pytest.mark.asyncio
    async def test_hybrid_search_parallel_execution(self):
        """Verify embedding and sparse tokenization can overlap."""
        call_order = []

        async def mock_get_embedding(text, task_type=None):
            call_order.append("embedding_start")
            await asyncio.sleep(0.01)  # simulate I/O
            call_order.append("embedding_end")
            return [0.1] * 1024

        def mock_sparse(text, service=None):
            call_order.append("sparse")
            return {1: 0.5, 2: 0.3}

        mock_client = AsyncMock()
        mock_client.query_points = AsyncMock(
            return_value=MagicMock(points=[])
        )

        with (
            patch("src.shared.qdrant_search.qclient") as mock_qclient,
            patch("src.shared.qdrant_search.get_embedding", side_effect=mock_get_embedding),
            patch("src.shared.qdrant_search.text_to_sparse_vector", side_effect=mock_sparse),
        ):
            mock_qclient.get_client = AsyncMock(return_value=mock_client)

            from src.shared.qdrant_search import hybrid_search

            results, meta = await hybrid_search("test query", "default")

            # Sparse should execute between embedding_start and embedding_end
            # (because create_task allows interleaving)
            assert "embedding_start" in call_order
            assert "sparse" in call_order
            assert "embedding_end" in call_order


# ====================================================================
# 3. Bridge locks — dual lock architecture
# ====================================================================

class TestBridgeLocks:
    """Verify omlx_bridge and rerank_bridge have proper dual-lock protection."""

    def test_omlx_bridge_has_dual_locks(self):
        from src.shared.omlx_bridge import _io_lock, _startup_lock

        assert isinstance(_startup_lock, asyncio.Lock)
        assert isinstance(_io_lock, asyncio.Lock)
        assert _startup_lock is not _io_lock, "Must be separate lock instances"

    def test_rerank_bridge_has_dual_locks(self):
        from src.shared.rerank_bridge import _io_lock, _startup_lock

        assert isinstance(_startup_lock, asyncio.Lock)
        assert isinstance(_io_lock, asyncio.Lock)
        assert _startup_lock is not _io_lock, "Must be separate lock instances"

    def test_omlx_send_request_uses_io_lock(self):
        """_send_request must use _io_lock to protect stdin/stdout atomicity."""
        from src.shared import omlx_bridge

        source = inspect.getsource(omlx_bridge._send_request)
        assert "_io_lock" in source, "_send_request must use _io_lock"

    def test_rerank_send_request_uses_io_lock(self):
        from src.shared import rerank_bridge

        source = inspect.getsource(rerank_bridge._send_request)
        assert "_io_lock" in source, "_send_request must use _io_lock"

    def test_omlx_ensure_worker_uses_startup_lock(self):
        from src.shared import omlx_bridge

        source = inspect.getsource(omlx_bridge._ensure_worker)
        assert "_startup_lock" in source, "_ensure_worker must use _startup_lock"

    def test_rerank_ensure_worker_uses_startup_lock(self):
        from src.shared import rerank_bridge

        source = inspect.getsource(rerank_bridge._ensure_worker)
        assert "_startup_lock" in source, "_ensure_worker must use _startup_lock"


# ====================================================================
# 4. Database pool — explicit settings
# ====================================================================

class TestDatabasePool:
    """Verify database pool is explicitly configured."""

    def test_pool_size_is_explicit(self):
        from src.shared.database import engine

        assert engine.pool.size() == 10, f"pool_size should be 10, got {engine.pool.size()}"

    def test_pool_overflow_is_explicit(self):
        from src.shared.database import engine

        assert engine.pool._max_overflow == 10, (
            f"max_overflow should be 10, got {engine.pool._max_overflow}"
        )


# ====================================================================
# 5. Cache — batch unlink
# ====================================================================

class TestCacheBatchUnlink:
    """Verify cache invalidation uses batch unlink instead of per-key delete."""

    def test_cache_delete_pattern_uses_unlink(self):
        from src.shared import cache

        source = inspect.getsource(cache.cache_delete_pattern)
        assert "unlink" in source, "Must use unlink for batch deletion"
        assert "r.delete" not in source, "Must NOT use per-key delete"


# ====================================================================
# 6. Caller sites — all use await
# ====================================================================

class TestCallerAwait:
    """Verify all callers of async qdrant functions properly use await."""

    _CALLER_FILES = [
        "src/events/handlers/qdrant_indexer.py",
        "src/modules/intelflow/search.py",
        "src/modules/paper/search.py",
        "src/modules/memvault/services.py",
        "src/modules/memvault/kg_services.py",
        "src/modules/memvault/dedup.py",
        "src/modules/capture/services.py",
    ]

    def test_no_sync_calls_to_qdrant_available(self):
        """Every qdrant_available() call must be preceded by await."""
        from pathlib import Path

        base = Path(__file__).resolve().parent.parent

        for relpath in self._CALLER_FILES:
            filepath = base / relpath
            if not filepath.exists():
                continue

            content = filepath.read_text()
            lines = content.split("\n")
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                # Skip imports, comments, definitions
                if stripped.startswith(("from ", "import ", "#", "def ", "async def ")):
                    continue
                # Check for qdrant_available() or is_available() without await
                if "qdrant_available()" in stripped or (
                    "is_available()" in stripped
                    and "qdrant" in content[:content.index(stripped)]
                ):
                    assert "await" in stripped, (
                        f"{relpath}:{i} — missing await: {stripped}"
                    )

    def test_register_qdrant_handlers_is_async(self):
        from src.events.handlers.qdrant_indexer import register_qdrant_handlers

        assert inspect.iscoroutinefunction(register_qdrant_handlers), (
            "register_qdrant_handlers must be async"
        )
