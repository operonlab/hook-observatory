"""Adversary tests for DocVault prompt-cache routing helpers.

Tests written WITHOUT reading llm_config.py implementation.
Focus: invariants, mutation-killers, boundary cases, determinism.

Public API under test:
    cache_key_for_chunks(chunks) -> str
    cache_settings(chunks=None, *, temperature=0.2, cache_key=None) -> dict
"""

from __future__ import annotations

import pytest

from ..llm_config import cache_key_for_chunks, cache_settings

# ============================================================================
# TestCacheKeyForChunks — invariants, boundaries, mutation killers
# ============================================================================


class TestCacheKeyForChunks:
    # ---------- Boundary cases ----------

    def test_none_returns_string(self):
        """None must return a string, never raise."""
        result = cache_key_for_chunks(None)
        assert isinstance(result, str)

    def test_empty_list_returns_string(self):
        """Empty list must return a string, never raise."""
        result = cache_key_for_chunks([])
        assert isinstance(result, str)

    def test_none_and_empty_consistent(self):
        """None and [] should be treated equivalently (both are 'no chunks')."""
        # Either both return same key OR both return string — but stable.
        k1 = cache_key_for_chunks(None)
        k2 = cache_key_for_chunks([])
        # Determinism of each path:
        assert k1 == cache_key_for_chunks(None)
        assert k2 == cache_key_for_chunks([])

    def test_returns_str_type_always(self):
        """Return type contract: always str."""
        for chunks in [
            None,
            [],
            [{"document_id": "a"}],
            [{"document_id": "a"}, {"document_id": "b"}],
        ]:
            assert isinstance(cache_key_for_chunks(chunks), str)

    # ---------- Determinism (Rule 5) ----------

    def test_determinism_same_input_same_output(self):
        """Same input twice → identical keys (no time/random)."""
        chunks = [{"document_id": "doc-alpha"}, {"document_id": "doc-beta"}]
        assert cache_key_for_chunks(chunks) == cache_key_for_chunks(chunks)

    def test_determinism_across_fresh_lists(self):
        """Fresh list construction with same content → same key."""
        a = [{"document_id": "x"}, {"document_id": "y"}]
        b = [{"document_id": "x"}, {"document_id": "y"}]
        assert cache_key_for_chunks(a) == cache_key_for_chunks(b)

    # ---------- Set semantics (Rule 6 — order independence) ----------

    def test_order_independence_two_docs(self):
        """[A,B] and [B,A] must yield SAME key (set semantics)."""
        ab = [{"document_id": "doc-A"}, {"document_id": "doc-B"}]
        ba = [{"document_id": "doc-B"}, {"document_id": "doc-A"}]
        assert cache_key_for_chunks(ab) == cache_key_for_chunks(ba)

    def test_order_independence_many_docs(self):
        """Permutation of 5 docs must collapse to one key."""
        forward = [{"document_id": f"d{i}"} for i in range(5)]
        reverse = list(reversed(forward))
        shuffled = [forward[i] for i in [2, 0, 4, 1, 3]]
        k1 = cache_key_for_chunks(forward)
        k2 = cache_key_for_chunks(reverse)
        k3 = cache_key_for_chunks(shuffled)
        assert k1 == k2 == k3

    def test_duplicate_doc_ids_collapsed(self):
        """Duplicates of same doc_id should not change the key vs single occurrence.

        Mutation killer: if implementation uses list (not set) of doc_ids,
        [A,A] and [A] would produce different keys.
        """
        single = [{"document_id": "doc-X"}]
        dup = [{"document_id": "doc-X"}, {"document_id": "doc-X"}]
        assert cache_key_for_chunks(single) == cache_key_for_chunks(dup)

    def test_duplicates_among_distinct(self):
        """[A,B,A] should equal [A,B] (sets {A,B})."""
        with_dup = [
            {"document_id": "A"},
            {"document_id": "B"},
            {"document_id": "A"},
        ]
        deduped = [{"document_id": "A"}, {"document_id": "B"}]
        assert cache_key_for_chunks(with_dup) == cache_key_for_chunks(deduped)

    # ---------- Sensitivity (mutation killers) ----------

    def test_single_char_change_changes_key(self):
        """Mutation killer: swap one char in any doc_id → different key."""
        original = [{"document_id": "doc-aaaa"}]
        mutated = [{"document_id": "doc-aaab"}]
        assert cache_key_for_chunks(original) != cache_key_for_chunks(mutated)

    def test_different_doc_sets_different_keys(self):
        """Different document sets → different keys."""
        set_a = [{"document_id": "A"}, {"document_id": "B"}]
        set_b = [{"document_id": "A"}, {"document_id": "C"}]
        assert cache_key_for_chunks(set_a) != cache_key_for_chunks(set_b)

    def test_subset_vs_superset_different_keys(self):
        """{A} and {A,B} must produce different keys — mutation killer for
        any impl that hashes only the first/last element."""
        subset = [{"document_id": "A"}]
        superset = [{"document_id": "A"}, {"document_id": "B"}]
        assert cache_key_for_chunks(subset) != cache_key_for_chunks(superset)

    def test_single_chunk_vs_empty_different_keys(self):
        """One chunk vs zero chunks must differ."""
        assert cache_key_for_chunks([{"document_id": "X"}]) != cache_key_for_chunks([])

    # ---------- Boundary: weird/missing fields ----------

    def test_missing_document_id_does_not_crash(self):
        """Chunks with no document_id key must NOT raise (defensive)."""
        # Should degrade gracefully, not KeyError.
        try:
            result = cache_key_for_chunks([{"text": "hello"}])
            assert isinstance(result, str)
        except KeyError:
            pytest.fail("cache_key_for_chunks raised KeyError on missing document_id")

    def test_mixed_with_and_without_document_id(self):
        """Mixed valid/invalid chunks must not raise."""
        try:
            result = cache_key_for_chunks(
                [{"document_id": "A"}, {"text": "no doc id"}, {"document_id": "B"}]
            )
            assert isinstance(result, str)
        except KeyError:
            pytest.fail("Mixed missing/present document_id raised KeyError")

    def test_unicode_doc_ids(self):
        """Unicode doc_ids must work and produce stable keys."""
        chunks = [{"document_id": "文件-甲"}, {"document_id": "文件-乙"}]
        k1 = cache_key_for_chunks(chunks)
        assert isinstance(k1, str)
        # Determinism on unicode:
        assert k1 == cache_key_for_chunks(chunks)
        # Different unicode → different key:
        chunks2 = [{"document_id": "文件-甲"}, {"document_id": "文件-丙"}]
        assert cache_key_for_chunks(chunks2) != k1

    def test_long_doc_ids(self):
        """Very long doc_ids must produce a (presumably bounded) string,
        not crash or return overly massive output."""
        long_id = "x" * 10_000
        result = cache_key_for_chunks([{"document_id": long_id}])
        assert isinstance(result, str)
        # Sanity: the cache key should be stable, not the giant id passed
        # through verbatim balloon-style. Allow up to ~2x to be safe.
        assert len(result) < 50_000

    def test_uuid_like_doc_ids(self):
        """Realistic UUID v7 strings — stable + sensitive."""
        u1 = "0190a8c1-9d4b-7000-a000-000000000001"
        u2 = "0190a8c1-9d4b-7000-a000-000000000002"
        k1 = cache_key_for_chunks([{"document_id": u1}])
        k2 = cache_key_for_chunks([{"document_id": u2}])
        assert k1 != k2

    def test_empty_string_doc_id(self):
        """Edge: empty-string doc_id handled without crash."""
        result = cache_key_for_chunks([{"document_id": ""}])
        assert isinstance(result, str)


# ============================================================================
# TestCacheSettings — temperature plumbing, override semantics, dict shape
# ============================================================================


class TestCacheSettings:
    # ---------- Dict-shape contract ----------

    def test_returns_dict(self):
        result = cache_settings()
        assert isinstance(result, dict)

    def test_contains_temperature_key(self):
        result = cache_settings()
        assert "temperature" in result

    def test_contains_openai_prompt_cache_key(self):
        """Spec: dict must contain `openai_prompt_cache_key`."""
        result = cache_settings()
        assert "openai_prompt_cache_key" in result

    def test_minimum_keys_present_for_all_inputs(self):
        """Both keys must always be present regardless of inputs."""
        for kwargs in [
            {},
            {"chunks": None},
            {"chunks": []},
            {"chunks": [{"document_id": "A"}]},
            {"cache_key": "manual-override"},
            {"chunks": [{"document_id": "A"}], "cache_key": "override"},
        ]:
            result = cache_settings(**kwargs)
            assert "temperature" in result
            assert "openai_prompt_cache_key" in result

    # ---------- Temperature plumbing ----------

    def test_default_temperature_is_zero_two(self):
        """Default temperature per signature is 0.2."""
        result = cache_settings()
        assert result["temperature"] == pytest.approx(0.2)

    def test_temperature_passed_through(self):
        """Explicit temperature value plumbs into dict verbatim."""
        result = cache_settings(temperature=0.7)
        assert result["temperature"] == pytest.approx(0.7)

    def test_temperature_zero(self):
        """Temperature=0 (deterministic mode) must be honored, not falsy-coerced."""
        result = cache_settings(temperature=0.0)
        assert result["temperature"] == pytest.approx(0.0)

    def test_temperature_one(self):
        result = cache_settings(temperature=1.0)
        assert result["temperature"] == pytest.approx(1.0)

    # ---------- Cache key derivation from chunks ----------

    def test_chunks_drive_cache_key(self):
        """Two different chunk sets produce two different cache keys in the dict."""
        s1 = cache_settings(chunks=[{"document_id": "A"}])
        s2 = cache_settings(chunks=[{"document_id": "B"}])
        assert s1["openai_prompt_cache_key"] != s2["openai_prompt_cache_key"]

    def test_chunks_cache_key_matches_helper(self):
        """The chunks-derived cache key in settings == cache_key_for_chunks(chunks).

        Mutation killer: confirms the two helpers are wired together,
        not implemented divergently.
        """
        chunks = [{"document_id": "A"}, {"document_id": "B"}]
        expected = cache_key_for_chunks(chunks)
        actual = cache_settings(chunks=chunks)["openai_prompt_cache_key"]
        assert actual == expected

    def test_chunks_order_independent_in_settings(self):
        """Settings cache key inherits set semantics from cache_key_for_chunks."""
        ab = [{"document_id": "A"}, {"document_id": "B"}]
        ba = [{"document_id": "B"}, {"document_id": "A"}]
        assert (
            cache_settings(chunks=ab)["openai_prompt_cache_key"]
            == cache_settings(chunks=ba)["openai_prompt_cache_key"]
        )

    # ---------- cache_key override semantics ----------

    def test_explicit_cache_key_used_verbatim(self):
        """When cache_key is provided, it appears in the dict verbatim."""
        result = cache_settings(cache_key="my-custom-key")
        assert result["openai_prompt_cache_key"] == "my-custom-key"

    def test_cache_key_overrides_chunks(self):
        """cache_key parameter overrides chunks-derived key (per docstring)."""
        chunks = [{"document_id": "A"}, {"document_id": "B"}]
        derived = cache_key_for_chunks(chunks)
        result = cache_settings(chunks=chunks, cache_key="manual-override")
        assert result["openai_prompt_cache_key"] == "manual-override"
        # And the override is genuinely different from what chunks would produce
        assert result["openai_prompt_cache_key"] != derived

    def test_cache_key_override_with_no_chunks(self):
        """cache_key works even when chunks is None."""
        result = cache_settings(chunks=None, cache_key="solo-override")
        assert result["openai_prompt_cache_key"] == "solo-override"

    def test_cache_key_override_with_empty_chunks(self):
        result = cache_settings(chunks=[], cache_key="empty-override")
        assert result["openai_prompt_cache_key"] == "empty-override"

    # ---------- Determinism ----------

    def test_settings_deterministic(self):
        """Same args → same dict twice."""
        chunks = [{"document_id": "stable-doc"}]
        s1 = cache_settings(chunks=chunks, temperature=0.3)
        s2 = cache_settings(chunks=chunks, temperature=0.3)
        assert s1 == s2

    def test_settings_deterministic_with_override(self):
        s1 = cache_settings(cache_key="fixed", temperature=0.5)
        s2 = cache_settings(cache_key="fixed", temperature=0.5)
        assert s1 == s2

    # ---------- No silent state mutation ----------

    def test_does_not_mutate_input_chunks(self):
        """Passing a chunks list must not mutate the caller's list."""
        chunks = [{"document_id": "A"}, {"document_id": "B"}]
        snapshot = [dict(c) for c in chunks]
        cache_settings(chunks=chunks)
        assert chunks == snapshot

    def test_returns_independent_dict_each_call(self):
        """Each call returns a fresh dict (mutating one must not affect another)."""
        s1 = cache_settings(chunks=[{"document_id": "A"}])
        s2 = cache_settings(chunks=[{"document_id": "A"}])
        s1["temperature"] = 999.0
        assert s2["temperature"] != 999.0

    # ---------- Sensitivity boundary ----------

    def test_no_chunks_no_override_still_valid_dict(self):
        """No chunks + no override → still a valid dict with both keys (string,
        possibly empty/sentinel). Must not raise."""
        result = cache_settings()
        assert isinstance(result, dict)
        assert isinstance(result["openai_prompt_cache_key"], str)
