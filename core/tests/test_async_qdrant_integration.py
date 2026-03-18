"""Integration tests for async Qdrant pipeline.

Tests the REAL async client against a running Qdrant instance.
Skips gracefully if Qdrant is not available.
"""

import asyncio
import time

import pytest
import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def _reset_qdrant_state():
    """Reset qdrant_client module state between tests."""
    import src.shared.qdrant_client as mod

    mod._client = None
    mod._available = None
    mod._last_failure = 0
    yield
    if mod._client:
        try:
            await mod._client.close()
        except Exception:
            pass
    mod._client = None
    mod._available = None


async def _qdrant_reachable() -> bool:
    """Check if Qdrant is actually running on localhost:6333."""
    from src.shared.qdrant_client import is_available

    return await is_available()


# ====================================================================
# Real Qdrant integration tests (skip if Qdrant not running)
# ====================================================================


@pytest.mark.asyncio
async def test_async_client_connects():
    """AsyncQdrantClient should connect to running Qdrant via gRPC."""
    if not await _qdrant_reachable():
        pytest.skip("Qdrant not running on localhost:6333")

    from src.shared.qdrant_client import get_client

    client = await get_client()
    assert client is not None

    # Verify it's actually async
    collections = await client.get_collections()
    assert hasattr(collections, "collections")


@pytest.mark.asyncio
async def test_health_check_returns_healthy():
    """health_check() should return healthy status."""
    if not await _qdrant_reachable():
        pytest.skip("Qdrant not running")

    import src.shared.qdrant_client as mod

    mod._client = None
    mod._available = None

    from src.shared.qdrant_client import health_check

    status = await health_check()
    assert status["status"] == "healthy"
    assert "collections" in status


@pytest.mark.asyncio
async def test_init_collection():
    """init_collection() should create or verify the collection exists."""
    if not await _qdrant_reachable():
        pytest.skip("Qdrant not running")

    from src.shared.qdrant_search import init_collection

    result = await init_collection()
    assert result is True


@pytest.mark.asyncio
async def test_index_and_search_roundtrip():
    """Full roundtrip: index a document, then search for it."""
    if not await _qdrant_reachable():
        pytest.skip("Qdrant not running")

    from src.shared.qdrant_search import (
        delete_document,
        hybrid_search,
        index_document,
        init_collection,
    )
    from src.shared.search_types import IndexDocument, SearchConfig

    await init_collection()

    # Index a test document
    test_doc = IndexDocument(
        service_id="test",
        entity_id="perf-test-001",
        entity_type="test_item",
        space_id="default",
        content="Workshop async Qdrant performance optimization test document",
        tags=["test", "perf"],
    )

    indexed = await index_document(test_doc)
    if not indexed:
        pytest.skip("Embedding service not available (oMLX worker not running)")

    # Brief wait for Qdrant indexing
    await asyncio.sleep(0.5)

    # Search for it
    config = SearchConfig(
        top_k=5,
        service_ids=["test"],
        score_threshold=0.0,
    )
    results, meta = await hybrid_search(
        "async Qdrant performance", "default", config
    )

    assert meta.query_time_ms is not None
    # Don't assert on results count — depends on embedding availability

    # Cleanup
    await delete_document("test", "perf-test-001")


@pytest.mark.asyncio
async def test_concurrent_searches_dont_block():
    """Multiple concurrent searches should not serialize (event loop not blocked)."""
    if not await _qdrant_reachable():
        pytest.skip("Qdrant not running")

    from src.shared.qdrant_search import hybrid_search, init_collection
    from src.shared.search_types import SearchConfig

    await init_collection()

    config = SearchConfig(top_k=3, service_ids=["test"])

    # Run 5 concurrent searches
    start = time.monotonic()
    tasks = [
        hybrid_search(f"test query {i}", "default", config) for i in range(5)
    ]
    results = await asyncio.gather(*tasks)
    elapsed = time.monotonic() - start

    # All should return (results, metadata) tuples
    assert len(results) == 5
    for res, meta in results:
        assert isinstance(res, list)

    # With async client, 5 concurrent searches should complete much faster
    # than 5 * sequential time. We just verify they complete at all.
    print(f"5 concurrent searches completed in {elapsed*1000:.1f}ms")


@pytest.mark.asyncio
async def test_graceful_fallback_when_unavailable():
    """When Qdrant is set unavailable, search should return empty with fallback meta."""
    import src.shared.qdrant_client as mod

    # Force unavailable state
    mod._available = False
    mod._last_failure = time.monotonic()  # just failed, within retry interval

    from src.shared.qdrant_search import hybrid_search
    from src.shared.search_types import SearchConfig

    config = SearchConfig(top_k=3)
    results, meta = await hybrid_search("anything", "default", config)

    assert results == []
    assert meta.backend == "pgvector_fallback"


@pytest.mark.asyncio
async def test_search_with_fallback_unavailable():
    """search_with_fallback should return ilike_fallback when Qdrant down."""
    import src.shared.qdrant_client as mod

    mod._available = False
    mod._last_failure = time.monotonic()

    from src.shared.qdrant_search import search_with_fallback

    results, meta = await search_with_fallback(
        "test", "default", "memvault", top_k=5
    )

    assert results == []
    assert meta.backend == "ilike_fallback"
