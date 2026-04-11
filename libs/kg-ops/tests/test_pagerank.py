"""Test-adversary: PPR functions — specification-driven, no implementation reading.

Invariants tested:
  - PageRank scores sum to ~1.0
  - Results sorted descending by score
  - top_k respected
  - Seed entities rank highest in PPR
  - Empty/degenerate inputs return []
  - Global PR identifies hub nodes
"""

import igraph as ig
import pytest

from kg_ops.community import build_entity_graph
from kg_ops.pagerank import global_pagerank, personalized_pagerank, ppr_from_triples


# ---- Fixtures ----


def _star_graph():
    """Hub 'A' connected to B, C, D, E. B-C also connected."""
    triples = [
        {"subject": "A", "object": "B"},
        {"subject": "A", "object": "C"},
        {"subject": "A", "object": "D"},
        {"subject": "A", "object": "E"},
        {"subject": "B", "object": "C"},
    ]
    return triples


def _chain_graph():
    """Linear: X → Y → Z → W."""
    return [
        {"subject": "X", "object": "Y"},
        {"subject": "Y", "object": "Z"},
        {"subject": "Z", "object": "W"},
    ]


def _disconnected_graph():
    """Two components: (A-B) and (C-D)."""
    return [
        {"subject": "A", "object": "B"},
        {"subject": "C", "object": "D"},
    ]


# ---- personalized_pagerank tests ----


class TestPersonalizedPageRank:
    def test_seed_entity_ranks_highest(self):
        triples = _star_graph()
        g, idx = build_entity_graph(triples)
        results = personalized_pagerank(g, ["A"], idx, top_k=5)
        assert len(results) > 0
        assert results[0][0] == "A", "Seed entity should rank highest"

    def test_sorted_descending(self):
        triples = _star_graph()
        g, idx = build_entity_graph(triples)
        results = personalized_pagerank(g, ["A"], idx, top_k=5)
        scores = [s for _, s in results]
        assert scores == sorted(scores, reverse=True)

    def test_top_k_respected(self):
        triples = _star_graph()
        g, idx = build_entity_graph(triples)
        results = personalized_pagerank(g, ["A"], idx, top_k=2)
        assert len(results) <= 2

    def test_invalid_seed_returns_empty(self):
        triples = _star_graph()
        g, idx = build_entity_graph(triples)
        results = personalized_pagerank(g, ["NonExistent"], idx, top_k=5)
        assert results == []

    def test_empty_graph_returns_empty(self):
        g = ig.Graph(n=0, directed=False)
        results = personalized_pagerank(g, ["A"], {}, top_k=5)
        assert results == []

    def test_multiple_seeds(self):
        triples = _disconnected_graph()
        g, idx = build_entity_graph(triples)
        results = personalized_pagerank(g, ["A", "C"], idx, top_k=4)
        names = {r[0] for r in results}
        # Both components should be represented
        assert "A" in names or "B" in names
        assert "C" in names or "D" in names

    def test_high_damping_stays_local(self):
        triples = _chain_graph()
        g, idx = build_entity_graph(triples)
        # High damping = stay close to seed
        results = personalized_pagerank(g, ["X"], idx, damping=0.99, top_k=4)
        # X should have much higher score than W (3 hops away)
        scores = dict(results)
        assert scores.get("X", 0) > scores.get("W", 0)

    def test_scores_positive(self):
        triples = _star_graph()
        g, idx = build_entity_graph(triples)
        results = personalized_pagerank(g, ["A"], idx, top_k=5)
        for _, score in results:
            assert score > 0


# ---- global_pagerank tests ----


class TestGlobalPageRank:
    def test_hub_node_ranks_high(self):
        triples = _star_graph()
        g, idx = build_entity_graph(triples)
        results = global_pagerank(g, top_k=5)
        # A is the hub (4 connections)
        assert results[0][0] == "A", f"Hub A should rank highest, got {results[0][0]}"

    def test_scores_sum_approximately_one(self):
        triples = _star_graph()
        g, idx = build_entity_graph(triples)
        results = global_pagerank(g, top_k=100)
        total = sum(s for _, s in results)
        assert 0.99 < total < 1.01, f"PR scores should sum to ~1.0, got {total}"

    def test_sorted_descending(self):
        triples = _star_graph()
        g, idx = build_entity_graph(triples)
        results = global_pagerank(g, top_k=5)
        scores = [s for _, s in results]
        assert scores == sorted(scores, reverse=True)

    def test_top_k_respected(self):
        triples = _star_graph()
        g, idx = build_entity_graph(triples)
        results = global_pagerank(g, top_k=2)
        assert len(results) <= 2

    def test_empty_graph(self):
        g = ig.Graph(n=0, directed=False)
        results = global_pagerank(g, top_k=5)
        assert results == []

    def test_single_node(self):
        g = ig.Graph(n=1, directed=False)
        g.vs["name"] = ["Solo"]
        results = global_pagerank(g, top_k=5)
        assert len(results) == 1
        assert results[0][0] == "Solo"
        assert abs(results[0][1] - 1.0) < 0.01  # only node gets all PR


# ---- ppr_from_triples tests ----


class TestPPRFromTriples:
    def test_basic_usage(self):
        triples = _star_graph()
        results = ppr_from_triples(triples, ["A"], top_k=3)
        assert len(results) > 0
        assert len(results) <= 3
        assert results[0][0] == "A"

    def test_empty_triples(self):
        results = ppr_from_triples([], ["A"], top_k=5)
        assert results == []

    def test_empty_seeds(self):
        triples = _star_graph()
        results = ppr_from_triples(triples, [], top_k=5)
        assert results == []

    def test_custom_keys(self):
        triples = [
            {"s": "Alpha", "o": "Beta"},
            {"s": "Beta", "o": "Gamma"},
        ]
        results = ppr_from_triples(
            triples, ["Alpha"], top_k=3,
            subject_key="s", object_key="o",
        )
        assert len(results) > 0
        names = {r[0] for r in results}
        assert "Alpha" in names  # seed must appear in results

    def test_chain_furthest_ranks_lowest(self):
        """In a chain X→Y→Z→W, PPR from X: W (furthest) should rank lowest."""
        triples = _chain_graph()
        results = ppr_from_triples(triples, ["X"], top_k=4, damping=0.85)
        scores = dict(results)
        # W is 3 hops from seed X — should have lowest score
        assert scores.get("W", 0) < scores.get("X", 0)
        assert scores.get("W", 0) < scores.get("Y", 0)
        assert scores.get("W", 0) < scores.get("Z", 0)

    def test_duplicate_triples_increase_weight(self):
        """Repeated triples should increase edge weight → affect scores."""
        single = [{"subject": "A", "object": "B"}, {"subject": "A", "object": "C"}]
        # B has more edges → should have slightly higher PPR from A
        double = single + [{"subject": "A", "object": "B"}]
        results_single = dict(ppr_from_triples(single, ["A"], top_k=3))
        results_double = dict(ppr_from_triples(double, ["A"], top_k=3))
        # With double edge to B, B's PPR should increase
        assert results_double.get("B", 0) >= results_single.get("B", 0)
