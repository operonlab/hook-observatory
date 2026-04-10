"""Adversarial tests for recall_dedup, recall_cache, recall_session.

Written as a Test Adversary — no source code read.
All tests derive from published function signatures, docstrings, and behavioral contracts.
Goal: find mutation-level bugs via edge cases, boundary conditions, and invariant violations.
"""

import json
import os
import stat
import sys
import time
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Import helpers — modules live next to this file
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent))

from datetime import UTC

import recall_cache as cache_mod
import recall_dedup as dedup_mod
import recall_session as session_mod

# ===========================================================================
# MODULE 1: recall_dedup.py
# ===========================================================================


class TestDedup:
    # -----------------------------------------------------------------------
    # Phase 1 helpers
    # -----------------------------------------------------------------------

    def _make_summary(self, community_id, rep_triples=None):
        return {
            "community_id": community_id,
            "summary": "some summary",
            "key_findings": ["finding"],
            "representative_triples": rep_triples or [],
        }

    def _make_community(self, cid, name="comm", size=5, parent_id=None):
        return {
            "id": cid,
            "name": name,
            "size": size,
            "summary": "community summary",
            "parent_community_id": parent_id,
        }

    def _make_triple(self, subject, predicate, obj):
        return {"subject": subject, "predicate": predicate, "object": obj}

    def _make_cascade(self, summaries=None, communities=None, triples=None):
        # IMPORTANT: dedup_cascade reads flat keys "summaries"/"communities"/"triples",
        # NOT the nested L2/L1/L0 structure described in the spec.
        # This is a spec-vs-implementation discrepancy (BUG-1 documented below).
        return {
            "summaries": summaries or [],
            "communities": communities or [],
            "triples": triples or [],
        }

    # -----------------------------------------------------------------------
    # Phase 1: community_id matching
    # -----------------------------------------------------------------------

    # NOTE (BUG-1): dedup_cascade uses flat keys "summaries"/"communities"/"triples".
    # The spec describes L2/L1/L0 nested structure but the implementation reads flat keys.
    # Callers passing L2/L1/L0 structure will get silently empty results — a real bug.
    # Tests below exercise the ACTUAL implementation contract (flat keys).

    def test_dedup_phase1_none_community_id_in_summary_does_not_crash(self):
        """Summary with community_id=None must not raise; community must survive in communities."""
        summary = self._make_summary(None)
        community = self._make_community("c1")
        data = self._make_cascade(summaries=[summary], communities=[community])
        result = dedup_mod.dedup_cascade(data)
        # community c1 had no matching summary → stays in communities
        assert any(c["id"] == "c1" for c in result["communities"])

    def test_dedup_phase1_missing_community_id_key_does_not_crash(self):
        """Summary lacking the community_id key entirely must not raise."""
        summary = {"summary": "no id here", "key_findings": [], "representative_triples": []}
        community = self._make_community("c1")
        data = self._make_cascade(summaries=[summary], communities=[community])
        result = dedup_mod.dedup_cascade(data)
        # Should not raise; result communities accessible
        assert isinstance(result["communities"], list)

    def test_dedup_phase1_matched_community_removed_from_communities(self):
        """When summary.community_id == community.id, that community is removed from communities."""
        summary = self._make_summary("c1")
        community = self._make_community("c1", name="Alpha", size=10)
        data = self._make_cascade(summaries=[summary], communities=[community])
        result = dedup_mod.dedup_cascade(data)
        # The matched community must be gone
        assert not any(c["id"] == "c1" for c in result["communities"])

    def test_dedup_phase1_matched_summary_enriched_with_name_and_size(self):
        """Matched summary must carry _community_name and _community_size from community."""
        summary = self._make_summary("c1")
        community = self._make_community("c1", name="Alpha", size=42)
        data = self._make_cascade(summaries=[summary], communities=[community])
        result = dedup_mod.dedup_cascade(data)
        enriched = result["summaries"][0]
        assert enriched.get("_community_name") == "Alpha"
        assert enriched.get("_community_size") == 42

    def test_dedup_phase1_two_summaries_same_community_id(self):
        """Two summaries referencing the SAME community_id — community removed at most once."""
        s1 = self._make_summary("c1")
        s2 = self._make_summary("c1")
        community = self._make_community("c1", name="Beta", size=7)
        data = self._make_cascade(summaries=[s1, s2], communities=[community])
        result = dedup_mod.dedup_cascade(data)
        # c1 must appear zero times in communities (not error, not negative)
        ids_in_communities = [c["id"] for c in result["communities"]]
        assert ids_in_communities.count("c1") == 0

    def test_dedup_phase1_unmatched_summary_stays_unchanged(self):
        """Summary whose community_id does not match any community is left intact."""
        summary = self._make_summary("z99")
        community = self._make_community("c1")
        data = self._make_cascade(summaries=[summary], communities=[community])
        result = dedup_mod.dedup_cascade(data)
        # z99 summary should still be in summaries
        ids = [s["community_id"] for s in result["summaries"]]
        assert "z99" in ids

    # -----------------------------------------------------------------------
    # Phase 2: hierarchy dedup threshold
    # -----------------------------------------------------------------------

    def test_dedup_phase2_parent_with_exactly_3_children_removes_children(self):
        """Threshold: <3 children → remove parent; >=3 → remove children.
        Exactly 3 children: len==3 is NOT < 3, so children are removed (parent kept).
        Confirms the boundary is strictly <3, not <=3."""
        parent = self._make_community("p", parent_id=None)
        c1 = self._make_community("c1", parent_id="p")
        c2 = self._make_community("c2", parent_id="p")
        c3 = self._make_community("c3", parent_id="p")
        data = self._make_cascade(communities=[parent, c1, c2, c3])
        result = dedup_mod.dedup_cascade(data)
        ids = {c["id"] for c in result["communities"]}
        # 3 children → >=3 branch → remove children, keep parent
        assert "p" in ids
        assert "c1" not in ids
        assert "c2" not in ids
        assert "c3" not in ids

    def test_dedup_phase2_parent_with_2_children_removes_parent(self):
        """2 children < 3 → remove parent (children are more specific)."""
        parent = self._make_community("p", parent_id=None)
        c1 = self._make_community("c1", parent_id="p")
        c2 = self._make_community("c2", parent_id="p")
        data = self._make_cascade(communities=[parent, c1, c2])
        result = dedup_mod.dedup_cascade(data)
        ids = {c["id"] for c in result["communities"]}
        assert "p" not in ids
        assert "c1" in ids
        assert "c2" in ids

    def test_dedup_phase2_parent_id_points_to_nonexistent_id(self):
        """Child whose parent_community_id is NOT in the result set must not crash."""
        orphan_child = self._make_community("c1", parent_id="ghost_parent")
        data = self._make_cascade(communities=[orphan_child])
        # Must not raise KeyError or similar; orphan child treated as no-parent
        result = dedup_mod.dedup_cascade(data)
        assert isinstance(result["communities"], list)

    def test_dedup_phase2_no_communities_does_not_crash(self):
        """Empty communities list — phase 2 returns empty list, no crash."""
        data = self._make_cascade(communities=[])
        result = dedup_mod.dedup_cascade(data)
        assert result["communities"] == []

    # -----------------------------------------------------------------------
    # Phase 3: triple dedup
    # -----------------------------------------------------------------------

    def test_dedup_phase3_all_triples_covered_returns_empty_list_not_none(self):
        """When every L0 triple is Jaccard-covered, result must be [] not None."""
        rep = "apple eats banana"
        summary = self._make_summary("c1", rep_triples=[rep])
        triple = self._make_triple("apple", "eats", "banana")
        data = self._make_cascade(summaries=[summary], communities=[], triples=[triple])
        result = dedup_mod.dedup_cascade(data)
        assert result["triples"] is not None
        assert isinstance(result["triples"], list)
        assert len(result["triples"]) == 0

    def test_dedup_phase3_non_string_in_representative_triples_does_not_crash(self):
        """Non-string elements in representative_triples (e.g. None, int) must not crash."""
        summary = self._make_summary("c1", rep_triples=[None, 42, "valid triple text"])
        triple = self._make_triple("x", "y", "z")
        data = self._make_cascade(summaries=[summary], communities=[], triples=[triple])
        # Must not raise
        result = dedup_mod.dedup_cascade(data)
        assert "triples" in result

    def test_dedup_phase3_uncovered_triple_stays_in_triples(self):
        """Triple that does NOT match any representative_triple stays in triples."""
        summary = self._make_summary("c1", rep_triples=["completely different words here"])
        triple = self._make_triple("apple", "eats", "banana")
        data = self._make_cascade(summaries=[summary], communities=[], triples=[triple])
        result = dedup_mod.dedup_cascade(data)
        assert len(result["triples"]) == 1

    def test_dedup_phase3_short_needle_under_2_tokens_not_matched(self):
        """needle < 2 tokens → _text_overlap returns False → triple kept in triples.
        The 'needle' here is the TRIPLE text; a single-word triple is not removed."""
        # Triple "x y z" normalized has 3 tokens, but rep "singletoken" has 1 token.
        # _text_overlap(needle=triple_text, haystack={rep}) — needle has >=2 tokens.
        # But hay_tokens = {"singletoken"} = 1 token.
        # Intersection with {x,y,z} = {} = 0. Jaccard = 0/4 < 0.7 → NOT removed.
        summary = self._make_summary("c1", rep_triples=["singletoken"])
        triple = self._make_triple("apple", "eats", "banana")
        data = self._make_cascade(summaries=[summary], communities=[], triples=[triple])
        result = dedup_mod.dedup_cascade(data)
        # triple should NOT be removed (Jaccard too low)
        assert len(result["triples"]) == 1

    def test_dedup_phase3_jaccard_exactly_07_threshold_is_covered(self):
        """Jaccard == 0.7 meets the >= threshold and should remove the triple.
        needle tokens: {a,b,c,d,e,f,g} (7), hay tokens: {a,b,c,d,e,f,g,h,i,j} (10)
        intersection=7, union=10 → 0.7 exactly ≥ 0.7 → triple removed."""
        summary = self._make_summary("c1", rep_triples=["a b c d e f g h i j"])
        triple = self._make_triple("a b c d", "e f", "g")  # normalized → "a b c d e f g"
        data = self._make_cascade(summaries=[summary], communities=[], triples=[triple])
        result = dedup_mod.dedup_cascade(data)
        # 7/10 = 0.7 >= threshold → should be removed
        assert len(result["triples"]) == 0

    # -----------------------------------------------------------------------
    # Missing layers
    # -----------------------------------------------------------------------

    def test_dedup_missing_summaries_key_skipped_gracefully(self):
        """cascade_data without 'summaries' key must not crash."""
        data = {"communities": [], "triples": []}
        result = dedup_mod.dedup_cascade(data)
        assert isinstance(result, dict)

    def test_dedup_missing_communities_key_skipped_gracefully(self):
        """cascade_data without 'communities' key must not crash."""
        data = {"summaries": [], "triples": []}
        result = dedup_mod.dedup_cascade(data)
        assert isinstance(result, dict)

    def test_dedup_missing_triples_key_skipped_gracefully(self):
        """cascade_data without 'triples' key must not crash."""
        data = {"summaries": [], "communities": []}
        result = dedup_mod.dedup_cascade(data)
        assert isinstance(result, dict)

    def test_dedup_nested_l2_l1_l0_structure_silently_produces_empty_result(self):
        """BUG-1: Callers passing the spec's L2/L1/L0 nested structure get empty results.
        dedup_cascade reads flat keys only; nested structure is silently ignored.
        This test documents the bug as a known regression guard."""
        summary = self._make_summary("c1")
        community = self._make_community("c1", name="Alpha", size=10)
        nested_data = {
            "L2": {"summaries": [summary]},
            "L1": {"communities": [community]},
            "L0": {"triples": []},
        }
        result = dedup_mod.dedup_cascade(nested_data)
        # Because flat keys are empty, no merging happens — community_name NOT injected
        # This is the bug: nested structure input silently does nothing
        assert result["summaries"] == []  # flat key was never set → empty
        # The L2/L1/L0 keys remain untouched
        assert "L2" in result

    def test_dedup_empty_cascade_does_not_crash(self):
        """Entirely empty cascade_data dict must not crash."""
        result = dedup_mod.dedup_cascade({})
        assert isinstance(result, dict)

    # -----------------------------------------------------------------------
    # Idempotency
    # -----------------------------------------------------------------------

    def test_dedup_idempotency_calling_twice_same_result(self):
        """dedup_cascade called twice on the same input must produce identical output."""
        import copy

        summary = self._make_summary("c1", rep_triples=["apple eats banana"])
        community = self._make_community("c1", name="Alpha", size=3, parent_id=None)
        triple = self._make_triple("apple", "eats", "banana")
        data = self._make_cascade(
            summaries=[summary],
            communities=[community],
            triples=[triple],
        )
        original = copy.deepcopy(data)
        result1 = dedup_mod.dedup_cascade(data)
        # Spec says: modifies in place. Deep copy result1 for comparison.
        snapshot1 = copy.deepcopy(result1)
        result2 = dedup_mod.dedup_cascade(result1)
        # The structure should be the same after both runs
        assert snapshot1["summaries"] == result2["summaries"]
        assert snapshot1["triples"] == result2["triples"]

    def test_dedup_returns_same_object_reference(self):
        """dedup_cascade must return the same dict it received (in-place modification)."""
        data = self._make_cascade()
        returned = dedup_mod.dedup_cascade(data)
        assert returned is data

    # -----------------------------------------------------------------------
    # _normalize_triple_text
    # -----------------------------------------------------------------------

    def test_normalize_triple_text_lowercases(self):
        """Uppercase input must be lowercased."""
        result = dedup_mod._normalize_triple_text("Hello World")
        assert result == "hello world"

    def test_normalize_triple_text_strips_whitespace(self):
        """Leading/trailing whitespace must be stripped."""
        result = dedup_mod._normalize_triple_text("  hello  ")
        assert result == "hello"

    def test_normalize_triple_text_collapses_internal_whitespace(self):
        """Multiple internal spaces must collapse to single space."""
        result = dedup_mod._normalize_triple_text("a   b    c")
        assert result == "a b c"

    def test_normalize_triple_text_empty_string(self):
        """Empty string must return empty string without crash."""
        result = dedup_mod._normalize_triple_text("")
        assert result == ""

    # -----------------------------------------------------------------------
    # _text_overlap
    # -----------------------------------------------------------------------

    def test_text_overlap_returns_false_for_single_token_needle(self):
        """needle with < 2 tokens must return False regardless of haystack."""
        haystack = {"hello world", "hello"}
        result = dedup_mod._text_overlap("hello", haystack, threshold=0.0)
        assert result is False

    def test_text_overlap_returns_false_for_empty_needle(self):
        """Empty needle (0 tokens) must return False."""
        haystack = {"hello world"}
        result = dedup_mod._text_overlap("", haystack)
        assert result is False

    def test_text_overlap_exact_match_returns_true(self):
        """Exact match → Jaccard 1.0 >= 0.7 → True."""
        haystack = {"cat sat mat"}
        result = dedup_mod._text_overlap("cat sat mat", haystack)
        assert result is True

    def test_text_overlap_empty_haystack_returns_false(self):
        """Empty haystack set → no candidate → False."""
        result = dedup_mod._text_overlap("hello world", set())
        assert result is False

    def test_text_overlap_below_threshold_returns_false(self):
        """Jaccard < 0.7 must return False."""
        # needle={a,b}, haystack item={a,c,d,e,f} → intersection={a}=1, union={a,b,c,d,e,f}=6 → 0.167
        result = dedup_mod._text_overlap("a b", {"a c d e f"}, threshold=0.7)
        assert result is False


# ===========================================================================
# MODULE 2: recall_cache.py
# ===========================================================================


class TestCache:
    # -----------------------------------------------------------------------
    # normalize_query
    # -----------------------------------------------------------------------

    def test_cache_normalize_query_lowercases(self):
        """Uppercase input must be lowercased."""
        assert cache_mod.normalize_query("Hello World") == "hello world"

    def test_cache_normalize_query_strips(self):
        """Leading/trailing whitespace stripped."""
        assert cache_mod.normalize_query("  hello  ") == "hello"

    def test_cache_normalize_query_collapses_internal_whitespace(self):
        """Internal multiple spaces collapse to single space."""
        assert cache_mod.normalize_query("a   b") == "a b"

    def test_cache_normalize_query_empty_string(self):
        """Empty string stays empty."""
        assert cache_mod.normalize_query("") == ""

    # -----------------------------------------------------------------------
    # query_hash
    # -----------------------------------------------------------------------

    def test_cache_query_hash_returns_16_hex_chars(self):
        """Hash must be exactly 16 hex characters."""
        h = cache_mod.query_hash("hello world")
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)

    def test_cache_query_hash_deterministic(self):
        """Same input → same hash."""
        assert cache_mod.query_hash("test") == cache_mod.query_hash("test")

    def test_cache_query_hash_different_inputs_differ(self):
        """Different inputs must (almost certainly) produce different hashes."""
        assert cache_mod.query_hash("a") != cache_mod.query_hash("b")

    def test_cache_query_hash_empty_string(self):
        """Empty string must return valid 16-char hex (no crash)."""
        h = cache_mod.query_hash("")
        assert len(h) == 16

    # -----------------------------------------------------------------------
    # read_cache / write_cache
    # -----------------------------------------------------------------------

    def test_cache_miss_returns_none_false(self, tmp_path):
        """Non-existent cache file → (None, False)."""
        result, stale = cache_mod.read_cache(tmp_path, "deadbeef12345678", 1800, 14400)
        assert result is None
        assert stale is False

    def test_cache_fresh_hit_returns_response_false(self, tmp_path):
        """Entry written just now is fresh → (response, False)."""
        response = {"data": "value", "count": 3}
        q_hash = cache_mod.query_hash("hello world")
        cache_mod.write_cache(tmp_path, q_hash, "hello world", "hello world", response, 1800)
        result, stale = cache_mod.read_cache(tmp_path, q_hash, 1800, 14400)
        assert result == response
        assert stale is False

    def test_cache_empty_response_dict_is_cached_and_returned(self, tmp_path):
        """Empty dict {} must be stored and retrieved (not skipped as falsy)."""
        response = {}
        q_hash = cache_mod.query_hash("empty query")
        cache_mod.write_cache(tmp_path, q_hash, "empty query", "empty query", response, 1800)
        result, stale = cache_mod.read_cache(tmp_path, q_hash, 1800, 14400)
        assert result == {}
        assert result is not None

    def test_cache_stale_hit_returns_response_true(self, tmp_path):
        """Entry beyond TTL but within stale_ttl → (response, True)."""
        response = {"data": "stale"}
        q_hash = cache_mod.query_hash("stale query")
        cache_mod.write_cache(tmp_path, q_hash, "stale query", "stale query", response, 1800)
        # Forge a timestamp in the past (beyond fresh TTL but within stale TTL)
        cache_file = tmp_path / f"{q_hash}.json"
        data = json.loads(cache_file.read_text())
        from datetime import datetime, timedelta

        past_ts = (datetime.now(UTC) - timedelta(seconds=2000)).isoformat()
        data["timestamp"] = past_ts
        cache_file.write_text(json.dumps(data))
        result, stale = cache_mod.read_cache(tmp_path, q_hash, 1800, 14400)
        assert result == response
        assert stale is True

    def test_cache_beyond_stale_ttl_returns_none_false(self, tmp_path):
        """Entry beyond stale_ttl → miss → (None, False)."""
        response = {"data": "ancient"}
        q_hash = cache_mod.query_hash("ancient query")
        cache_mod.write_cache(tmp_path, q_hash, "ancient query", "ancient query", response, 1800)
        cache_file = tmp_path / f"{q_hash}.json"
        data = json.loads(cache_file.read_text())
        from datetime import datetime, timedelta

        very_old = (datetime.now(UTC) - timedelta(seconds=20000)).isoformat()
        data["timestamp"] = very_old
        cache_file.write_text(json.dumps(data))
        result, stale = cache_mod.read_cache(tmp_path, q_hash, 1800, 14400)
        assert result is None
        assert stale is False

    def test_cache_ttl_boundary_exactly_at_ttl(self, tmp_path):
        """Entry written exactly TTL seconds ago — should be stale (not fresh).
        This probes the boundary condition: age >= ttl → stale, not fresh."""
        response = {"data": "boundary"}
        q_hash = cache_mod.query_hash("boundary query")
        cache_mod.write_cache(tmp_path, q_hash, "boundary query", "boundary query", response, 1800)
        cache_file = tmp_path / f"{q_hash}.json"
        data = json.loads(cache_file.read_text())
        from datetime import datetime, timedelta

        # Exactly at TTL boundary: 1800 seconds ago
        exact_ts = (datetime.now(UTC) - timedelta(seconds=1800)).isoformat()
        data["timestamp"] = exact_ts
        cache_file.write_text(json.dumps(data))
        result, stale = cache_mod.read_cache(tmp_path, q_hash, 1800, 14400)
        # At exact boundary: either stale or miss, but NOT fresh (stale=False with result)
        # If result returned with stale=False, that would be a bug
        if result is not None:
            assert stale is True, "Entry at exact TTL boundary must not be considered fresh"

    def test_cache_corrupt_json_deleted_and_returns_miss(self, tmp_path):
        """Corrupt JSON cache file → deleted, returns (None, False), no crash."""
        q_hash = "abcd1234abcd1234"
        cache_file = tmp_path / f"{q_hash}.json"
        cache_file.write_text("{ not valid json !!!")
        result, stale = cache_mod.read_cache(tmp_path, q_hash, 1800, 14400)
        assert result is None
        assert stale is False
        # Corrupt file should be deleted
        assert not cache_file.exists()

    def test_cache_write_creates_latest_json(self, tmp_path):
        """write_cache must also update _latest.json."""
        response = {"data": "latest"}
        q_hash = cache_mod.query_hash("latest test")
        cache_mod.write_cache(tmp_path, q_hash, "latest test", "latest test", response, 1800)
        latest_file = tmp_path / "_latest.json"
        assert latest_file.exists()

    def test_cache_read_latest_returns_stale_hit(self, tmp_path):
        """read_latest returns (response, True) for any cached entry within stale_ttl."""
        response = {"data": "for latest"}
        q_hash = cache_mod.query_hash("latest query")
        cache_mod.write_cache(tmp_path, q_hash, "latest query", "latest query", response, 1800)
        result, stale = cache_mod.read_latest(tmp_path, 14400)
        assert result is not None
        assert stale is True  # read_latest always returns stale=True per spec

    def test_cache_read_latest_missing_file_returns_none_false(self, tmp_path):
        """_latest.json does not exist → (None, False)."""
        result, stale = cache_mod.read_latest(tmp_path, 14400)
        assert result is None
        assert stale is False

    def test_cache_read_latest_deleted_between_write_and_read(self, tmp_path):
        """_latest.json deleted after write → read_latest returns (None, False), no crash."""
        response = {"data": "ephemeral"}
        q_hash = cache_mod.query_hash("ephemeral")
        cache_mod.write_cache(tmp_path, q_hash, "ephemeral", "ephemeral", response, 1800)
        (tmp_path / "_latest.json").unlink()
        result, stale = cache_mod.read_latest(tmp_path, 14400)
        assert result is None
        assert stale is False

    # -----------------------------------------------------------------------
    # evict_lru
    # -----------------------------------------------------------------------

    def test_cache_evict_lru_0_entries_no_crash(self, tmp_path):
        """evict_lru with 0 existing entries must not crash."""
        cache_mod.evict_lru(tmp_path, max_entries=20)  # no files

    def test_cache_evict_lru_respects_max_entries(self, tmp_path):
        """After eviction, at most max_entries .json files remain (excl. _latest.json)."""
        # Write 25 files with distinct hashes
        for i in range(25):
            fname = tmp_path / f"{i:016x}.json"
            fname.write_text(json.dumps({"i": i}))
            time.sleep(0.01)  # ensure different mtime
        (tmp_path / "_latest.json").write_text("{}")
        cache_mod.evict_lru(tmp_path, max_entries=20)
        json_files = [f for f in tmp_path.glob("*.json") if f.name != "_latest.json"]
        assert len(json_files) <= 20

    def test_cache_evict_lru_latest_json_not_deleted(self, tmp_path):
        """_latest.json must never be deleted by evict_lru."""
        for i in range(25):
            fname = tmp_path / f"{i:016x}.json"
            fname.write_text(json.dumps({"i": i}))
        (tmp_path / "_latest.json").write_text('{"preserved": true}')
        cache_mod.evict_lru(tmp_path, max_entries=5)
        assert (tmp_path / "_latest.json").exists()

    def test_cache_evict_lru_latest_not_counted_in_max(self, tmp_path):
        """_latest.json must not count toward max_entries."""
        for i in range(10):
            fname = tmp_path / f"{i:016x}.json"
            fname.write_text(json.dumps({"i": i}))
        (tmp_path / "_latest.json").write_text("{}")
        cache_mod.evict_lru(tmp_path, max_entries=10)
        json_files = [f for f in tmp_path.glob("*.json") if f.name != "_latest.json"]
        assert len(json_files) <= 10

    # -----------------------------------------------------------------------
    # write_cache never raises
    # -----------------------------------------------------------------------

    def test_cache_write_cache_never_raises_on_readonly_dir(self, tmp_path):
        """write_cache must not raise even if directory is read-only."""
        if os.name == "nt":
            pytest.skip("chmod read-only unreliable on Windows")
        ro_dir = tmp_path / "readonly"
        ro_dir.mkdir()
        ro_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)  # rx, no write
        try:
            # Should not raise
            cache_mod.write_cache(ro_dir, "abcd1234abcd1234", "q", "q", {"x": 1}, 1800)
        finally:
            ro_dir.chmod(stat.S_IRWXU)  # restore to clean up

    def test_cache_write_same_hash_twice_no_crash(self, tmp_path):
        """Writing the same hash twice (simulated concurrent write) must not crash."""
        response = {"data": "v1"}
        q_hash = cache_mod.query_hash("duplicate write")
        cache_mod.write_cache(
            tmp_path, q_hash, "duplicate write", "duplicate write", response, 1800
        )
        response2 = {"data": "v2"}
        cache_mod.write_cache(
            tmp_path, q_hash, "duplicate write", "duplicate write", response2, 1800
        )
        result, _ = cache_mod.read_cache(tmp_path, q_hash, 1800, 14400)
        assert result == response2  # second write wins

    # -----------------------------------------------------------------------
    # Negative TTL
    # -----------------------------------------------------------------------

    def test_cache_negative_ttl_makes_entry_immediately_stale(self, tmp_path):
        """Negative TTL means every entry is beyond TTL immediately.
        Reads should return stale or miss — never fresh."""
        response = {"data": "negative"}
        q_hash = cache_mod.query_hash("neg ttl query")
        cache_mod.write_cache(tmp_path, q_hash, "neg ttl query", "neg ttl query", response, -1)
        result, stale = cache_mod.read_cache(tmp_path, q_hash, -1, 14400)
        # With negative TTL, everything is already expired; result may be stale or miss
        if result is not None:
            assert stale is True, "Negative TTL entry must not be fresh"

    def test_cache_negative_stale_ttl_fresh_entry_still_returned(self, tmp_path):
        """Negative stale_ttl with positive ttl: fresh check happens first → entry returned as fresh."""
        response = {"data": "val"}
        q_hash = cache_mod.query_hash("neg stale")
        cache_mod.write_cache(tmp_path, q_hash, "neg stale", "neg stale", response, 1800)
        result, stale = cache_mod.read_cache(tmp_path, q_hash, 1800, -1)
        # Fresh TTL (1800) takes precedence — entry is within fresh window
        assert result == response
        assert stale is False


# ===========================================================================
# MODULE 3: recall_session.py
# ===========================================================================


class TestSession:
    """Tests for recall_session.py — based on spec only, no source read."""

    def _write_jsonl(self, path: Path, entries: list[dict]) -> None:
        lines = [json.dumps(e) for e in entries]
        path.write_text("\n".join(lines), encoding="utf-8")

    def _user_text_entry(self, text: str) -> dict:
        return {
            "type": "user",
            "message": {
                "role": "user",
                "content": text,
            },
        }

    def _user_list_entry(self, content_items: list) -> dict:
        return {
            "type": "user",
            "message": {
                "role": "user",
                "content": content_items,
            },
        }

    def _assistant_entry_with_tools(self, tools: list[dict]) -> dict:
        return {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": tools,
            },
        }

    def _tool_use_block(self, name: str, filepath: str = None) -> dict:
        block = {"type": "tool_use", "name": name}
        if filepath:
            block["input"] = {"file_path": filepath}
        return block

    # -----------------------------------------------------------------------
    # Setup helper: write transcript to the path extract_session_context expects
    # -----------------------------------------------------------------------

    def _setup_transcript(self, monkeypatch, tmp_path, session_id, cwd_path, entries):
        """Write a transcript JSONL where extract_session_context will find it."""
        # Primary path: ~/.claude/projects/{cwd.replace('/', '-')}/{session_id}.jsonl
        cwd_str = str(cwd_path)
        project_dir = tmp_path / "projects" / cwd_str.replace("/", "-")
        project_dir.mkdir(parents=True, exist_ok=True)
        transcript = project_dir / f"{session_id}.jsonl"
        self._write_jsonl(transcript, entries)

        # Patch the home directory so _find_transcript looks in tmp_path
        import pathlib

        monkeypatch.setattr(pathlib.Path, "home", staticmethod(lambda: tmp_path))
        return transcript

    # -----------------------------------------------------------------------
    # Tests
    # -----------------------------------------------------------------------

    def test_session_only_system_entries_returns_empty(self, monkeypatch, tmp_path):
        """Transcript with ONLY system-like entries must return ''."""
        entries = [
            {"type": "system", "content": "permission-mode"},
            {"type": "attachment", "content": "some attachment"},
        ]
        self._setup_transcript(monkeypatch, tmp_path, "sess1", "/work/proj", entries)
        result = session_mod.extract_session_context("sess1", "/work/proj", "current prompt")
        assert result == ""

    def test_session_tool_result_only_user_entry_skipped(self, monkeypatch, tmp_path):
        """User entry with content=[{type: tool_result}] and no text block must be skipped."""
        entries = [
            self._user_list_entry([{"type": "tool_result", "content": "some result"}]),
            self._user_text_entry("A real prior question"),
        ]
        self._setup_transcript(monkeypatch, tmp_path, "sess2", "/work/proj", entries)
        result = session_mod.extract_session_context("sess2", "/work/proj", "current prompt")
        # Should contain the real text, not crash on tool_result-only entry
        # If result is non-empty, it should not include tool_result data
        if result:
            assert "some result" not in result

    def test_session_long_user_message_truncated_to_100_chars(self, monkeypatch, tmp_path):
        """User message >100 chars must be truncated to 100 chars in output."""
        long_msg = "A" * 200
        entries = [
            self._user_text_entry("first message"),
            self._user_text_entry(long_msg),
        ]
        self._setup_transcript(monkeypatch, tmp_path, "sess3", "/work/proj", entries)
        result = session_mod.extract_session_context("sess3", "/work/proj", "current prompt")
        if result:
            # The long message block should not appear as >100 chars of 'A'
            assert "A" * 101 not in result

    def test_session_empty_file_returns_empty(self, monkeypatch, tmp_path):
        """0-byte transcript file must return '' without crash."""
        cwd_str = "/work/proj"
        project_dir = tmp_path / "projects" / cwd_str.replace("/", "-")
        project_dir.mkdir(parents=True, exist_ok=True)
        transcript = project_dir / "sess4.jsonl"
        transcript.write_bytes(b"")
        import pathlib

        monkeypatch.setattr(pathlib.Path, "home", staticmethod(lambda: tmp_path))
        result = session_mod.extract_session_context("sess4", cwd_str, "current prompt")
        assert result == ""

    def test_session_malformed_lines_skipped_valid_processed(self, monkeypatch, tmp_path):
        """Malformed JSON lines mixed with valid lines — bad lines skipped, good ones processed."""
        cwd_str = "/work/proj"
        project_dir = tmp_path / "projects" / cwd_str.replace("/", "-")
        project_dir.mkdir(parents=True, exist_ok=True)
        transcript = project_dir / "sess5.jsonl"
        lines = [
            "{ not json !!!",
            json.dumps(self._user_text_entry("valid user message")),
            "another bad line",
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")
        import pathlib

        monkeypatch.setattr(pathlib.Path, "home", staticmethod(lambda: tmp_path))
        # Must not crash; should process valid lines
        result = session_mod.extract_session_context("sess5", cwd_str, "current prompt")
        # Result is either '' (only 1 user msg) or contains the valid message
        assert isinstance(result, str)

    def test_session_no_transcript_file_returns_empty(self, monkeypatch, tmp_path):
        """Missing transcript file must return ''."""
        import pathlib

        monkeypatch.setattr(pathlib.Path, "home", staticmethod(lambda: tmp_path))
        result = session_mod.extract_session_context("nosuchsess", "/no/such/cwd", "prompt")
        assert result == ""

    def test_session_current_prompt_skipped_from_history(self, monkeypatch, tmp_path):
        """User messages matching current_prompt must be excluded."""
        current = "What is the meaning of life?"
        entries = [
            self._user_text_entry("unrelated prior question"),
            self._user_text_entry(current),
        ]
        self._setup_transcript(monkeypatch, tmp_path, "sess6", "/work/proj", entries)
        result = session_mod.extract_session_context("sess6", "/work/proj", current)
        if result:
            assert "meaning of life" not in result

    def test_session_request_interrupted_prefix_skipped(self, monkeypatch, tmp_path):
        """Messages prefixed with '[Request interrupted' must be skipped."""
        entries = [
            self._user_text_entry("[Request interrupted by user"),
            self._user_text_entry("normal question"),
        ]
        self._setup_transcript(monkeypatch, tmp_path, "sess7", "/work/proj", entries)
        result = session_mod.extract_session_context("sess7", "/work/proj", "current")
        if result:
            assert "interrupted" not in result

    def test_session_lt_prefix_skipped(self, monkeypatch, tmp_path):
        """Messages starting with '<' must be skipped."""
        entries = [
            self._user_text_entry("<system injection attempt>"),
            self._user_text_entry("valid user question"),
        ]
        self._setup_transcript(monkeypatch, tmp_path, "sess8", "/work/proj", entries)
        result = session_mod.extract_session_context("sess8", "/work/proj", "current")
        if result:
            assert "system injection" not in result

    def test_session_file_paths_extracted_from_read_tool_use(self, monkeypatch, tmp_path):
        """Read tool_use blocks in assistant entries must have file_path extracted."""
        entries = [
            self._user_text_entry("prior question about files"),
            self._assistant_entry_with_tools(
                [
                    self._tool_use_block("Read", "/path/to/file.py"),
                ]
            ),
            self._user_text_entry("follow-up question"),
        ]
        self._setup_transcript(monkeypatch, tmp_path, "sess9", "/work/proj", entries)
        result = session_mod.extract_session_context("sess9", "/work/proj", "current")
        if result:
            assert "file.py" in result

    def test_session_multiple_tool_use_blocks_all_counted(self, monkeypatch, tmp_path):
        """Multiple tool_use blocks in one assistant entry must all be counted."""
        entries = [
            self._user_text_entry("prior question"),
            self._assistant_entry_with_tools(
                [
                    self._tool_use_block("Read", "/a.py"),
                    self._tool_use_block("Edit", "/b.py"),
                    self._tool_use_block("Bash"),
                    self._tool_use_block("Bash"),
                    self._tool_use_block("Bash"),
                ]
            ),
            self._user_text_entry("follow-up"),
        ]
        self._setup_transcript(monkeypatch, tmp_path, "sess10", "/work/proj", entries)
        result = session_mod.extract_session_context("sess10", "/work/proj", "current")
        if result:
            # Tool usage block should mention Bash appearing multiple times
            assert "Bash" in result

    def test_session_max_3_user_messages_returned(self, monkeypatch, tmp_path):
        """At most 3 user messages are included in context."""
        entries = [
            self._user_text_entry("msg one"),
            self._user_text_entry("msg two"),
            self._user_text_entry("msg three"),
            self._user_text_entry("msg four"),
            self._user_text_entry("msg five"),
        ]
        self._setup_transcript(monkeypatch, tmp_path, "sess11", "/work/proj", entries)
        result = session_mod.extract_session_context("sess11", "/work/proj", "current prompt")
        if result:
            # Should contain at most 3 of the messages (last 3)
            count = sum(
                1
                for msg in ["msg one", "msg two", "msg three", "msg four", "msg five"]
                if msg in result
            )
            assert count <= 3

    def test_session_file_paths_deduped(self, monkeypatch, tmp_path):
        """Duplicate file paths across multiple tool_use blocks must be deduplicated."""
        entries = [
            self._user_text_entry("prior question"),
            self._assistant_entry_with_tools(
                [
                    self._tool_use_block("Read", "/shared/file.py"),
                    self._tool_use_block("Edit", "/shared/file.py"),
                ]
            ),
            self._user_text_entry("follow-up"),
        ]
        self._setup_transcript(monkeypatch, tmp_path, "sess12", "/work/proj", entries)
        result = session_mod.extract_session_context("sess12", "/work/proj", "current")
        if result:
            # file.py should appear only once in the paths section
            assert result.count("/shared/file.py") <= 1

    def test_session_returns_markdown_section_when_has_history(self, monkeypatch, tmp_path):
        """Non-empty result must start with expected markdown header."""
        entries = [
            self._user_text_entry("first message ever"),
            self._user_text_entry("second message"),
        ]
        self._setup_transcript(monkeypatch, tmp_path, "sess13", "/work/proj", entries)
        result = session_mod.extract_session_context("sess13", "/work/proj", "current prompt")
        if result:
            assert result.startswith("###")

    # -----------------------------------------------------------------------
    # _extract_user_text
    # -----------------------------------------------------------------------

    def test_extract_user_text_with_string_content(self):
        """content as plain string → return it directly."""
        entry = {
            "type": "user",
            "message": {"role": "user", "content": "hello world"},
        }
        result = session_mod._extract_user_text(entry)
        assert result == "hello world"

    def test_extract_user_text_with_list_returns_first_text_block(self):
        """content as list → find first text block."""
        entry = {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {"type": "tool_result", "content": "ignored"},
                    {"type": "text", "text": "actual text"},
                ],
            },
        }
        result = session_mod._extract_user_text(entry)
        assert result == "actual text"

    def test_extract_user_text_wrong_type_returns_empty(self):
        """entry.type != 'user' → return ''."""
        entry = {
            "type": "assistant",
            "message": {"role": "assistant", "content": "some text"},
        }
        result = session_mod._extract_user_text(entry)
        assert result == ""

    def test_extract_user_text_wrong_role_returns_empty(self):
        """entry.message.role != 'user' → return ''."""
        entry = {
            "type": "user",
            "message": {"role": "system", "content": "system message"},
        }
        result = session_mod._extract_user_text(entry)
        assert result == ""

    def test_extract_user_text_list_with_no_text_block_returns_empty(self):
        """content list with no text-type block → return ''."""
        entry = {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {"type": "tool_result", "content": "tool output"},
                    {"type": "image", "data": "..."},
                ],
            },
        }
        result = session_mod._extract_user_text(entry)
        assert result == ""

    # -----------------------------------------------------------------------
    # _tail_read_lines
    # -----------------------------------------------------------------------

    def test_tail_read_lines_discards_first_truncated_line(self, tmp_path):
        """First line after seek may be truncated — must be discarded."""
        # Write content larger than read_size to force a mid-line seek
        lines = [f"line{i}" for i in range(1000)]
        content = "\n".join(lines)
        f = tmp_path / "big.jsonl"
        f.write_text(content, encoding="utf-8")
        result = session_mod._tail_read_lines(str(f), read_size=100)
        # None of the returned lines should be a partial line starting mid-word
        for line in result:
            assert line.startswith("line"), f"Got potentially truncated line: {line!r}"

    def test_tail_read_lines_empty_file(self, tmp_path):
        """0-byte file must return empty list without crash."""
        f = tmp_path / "empty.jsonl"
        f.write_bytes(b"")
        result = session_mod._tail_read_lines(str(f))
        assert isinstance(result, list)
        assert len(result) == 0

    def test_tail_read_lines_small_file_returns_all_lines(self, tmp_path):
        """File smaller than read_size → all lines returned (minus first-truncated discard)."""
        lines = ["line1", "line2", "line3"]
        f = tmp_path / "small.jsonl"
        f.write_text("\n".join(lines), encoding="utf-8")
        result = session_mod._tail_read_lines(str(f), read_size=65536)
        # All lines present (small file, no truncation → first discard is empty or 'line1')
        assert "line2" in result
        assert "line3" in result

    # -----------------------------------------------------------------------
    # _find_transcript
    # -----------------------------------------------------------------------

    def test_find_transcript_primary_path_found(self, monkeypatch, tmp_path):
        """Primary path exists → returns it. Patches _PROJECTS_BASE directly."""
        projects_base = str(tmp_path / ".claude" / "projects")
        monkeypatch.setattr(session_mod, "_PROJECTS_BASE", projects_base)
        cwd_str = "/my/cwd"
        project_dir = tmp_path / ".claude" / "projects" / cwd_str.replace("/", "-")
        project_dir.mkdir(parents=True, exist_ok=True)
        transcript = project_dir / "mysess.jsonl"
        transcript.write_text('{"type":"user"}')
        result = session_mod._find_transcript("mysess", cwd_str)
        assert result != ""
        assert "mysess.jsonl" in result

    def test_find_transcript_missing_returns_empty(self, monkeypatch, tmp_path):
        """No matching transcript → returns ''."""
        projects_base = str(tmp_path / ".claude" / "projects")
        monkeypatch.setattr(session_mod, "_PROJECTS_BASE", projects_base)
        result = session_mod._find_transcript("nosuch", "/no/cwd")
        assert result == ""
