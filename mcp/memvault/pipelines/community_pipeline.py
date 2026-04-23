#!/usr/bin/env python3
"""community_pipeline.py — Memvault V2 Knowledge Graph: Leiden Community Detection Pipeline

Fetches all triples from Core API, builds an entity co-occurrence graph,
runs Leiden community detection at 3 resolution levels, and POSTs community
results back to Core API.

Usage:
    python3 community_pipeline.py [--space-id default] [--dry-run]
    ~/.local/bin/python3 community_pipeline.py

Dependencies: igraph (python-igraph), leidenalg
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime
from urllib.parse import urlencode

# ── Configuration ──────────────────────────────────────────────────────────────
CORE_API = os.environ.get("CORE_API_URL", "http://localhost:10000")
MAX_TRIPLES_PER_FETCH = 20000

RESOLUTIONS = {
    0: 1.0,  # fine: many small communities
    1: 0.3,  # medium
    2: 0.05,  # coarse: few large themes
}

JUDGMENT_PREDICATES = {"should", "should_NOT", "chosen_over"}
RESULT_PREDICATES = {"improves", "fixes", "enables", "prevents"}
CONTEXT_PREDICATES = {"causes", "requires", "depends_on", "uses"}


# ── HTTP helpers (stdlib only, no external deps) ──────────────────────────────
def http_get(url: str, params: dict | None = None) -> dict:
    if params:
        url = f"{url}?{urlencode(params)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        print(f"[error] GET {url} → HTTP {e.code}: {body}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"[error] GET {url} → {e}", file=sys.stderr)
        sys.exit(1)


def http_post(url: str, body: dict, params: dict | None = None) -> dict:
    if params:
        url = f"{url}?{urlencode(params)}"
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode("utf-8", errors="replace")[:200]
        print(f"[error] POST {url} → HTTP {e.code}: {body_txt}", file=sys.stderr)
        return {"error": e.code}
    except urllib.error.URLError as e:
        print(f"[error] POST {url} → {e}", file=sys.stderr)
        return {"error": str(e)}


# ── Phase 1: Fetch Triples from Core API (paginated) ─────────────────────────
def fetch_triples(space_id: str) -> list[dict]:
    url = f"{CORE_API}/api/memvault/kg/triples"
    page_size = 100
    page = 1
    rows: list[dict] = []
    total = None

    print(f"[Phase 1] Fetching triples from {url} (space={space_id}) ...")

    while True:
        params = {"space_id": space_id, "page_size": page_size, "page": page}
        data = http_get(url, params)

        items = data.get("items", []) if isinstance(data, dict) else data
        if total is None:
            total = data.get("total", 0) if isinstance(data, dict) else len(items)

        if not items:
            break

        for item in items:
            s = (item.get("s") or item.get("subject") or "").strip()
            p = (item.get("p") or item.get("predicate") or "").strip()
            o = (item.get("o") or item.get("object") or "").strip()
            if s and p and o:
                rows.append(
                    {
                        "id": item.get("id", ""),
                        "s": s,
                        "p": p,
                        "o": o,
                        "text": f"{s} {p} {o}",
                        "session_id": item.get("session_id", ""),
                        "topic": item.get("topic", ""),
                        "tags": item.get("tags", []),
                    }
                )

        if len(items) < page_size:
            break
        if len(rows) >= MAX_TRIPLES_PER_FETCH:
            break
        page += 1

    print(f"[Phase 1] Loaded {len(rows)} triples (API total: {total})")
    return rows


# ── Phase 2: Build Entity Co-occurrence Graph ─────────────────────────────────
def ensure_igraph() -> None:
    """Install igraph if not present."""
    try:
        import igraph  # noqa: F401
    except ImportError:
        print("[Phase 2] igraph not found — installing via uv...")
        result = subprocess.run(
            [
                "/opt/homebrew/bin/uv",
                "pip",
                "install",
                "igraph",
                "leidenalg",
                "--python",
                sys.executable,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"[error] Failed to install igraph:\n{result.stderr}", file=sys.stderr)
            sys.exit(1)
        print("[Phase 2] igraph + leidenalg installed.")


def _fetch_entity_edges(space_id: str) -> list[dict] | None:
    """Try to fetch precomputed multi-signal entity edges from Core API.

    Returns list of edge dicts with entity_a_name, entity_b_name, composite_weight,
    or None if unavailable (API down, no edges yet, etc.).
    """
    url = f"{CORE_API}/api/memvault/kg/entity-edges"
    try:
        edges = http_get(url, params={"space_id": space_id, "min_weight": 0.01, "limit": 5000})
        if isinstance(edges, list) and len(edges) > 0:
            print(f"[Phase 2] Fetched {len(edges)} precomputed entity edges from API")
            return edges
        return None
    except SystemExit:
        # http_get calls sys.exit on error — catch and fall through
        return None
    except Exception:
        return None


def build_entity_graph(rows: list[dict], space_id: str = "default"):
    """Build undirected graph: entities as vertices, weighted edges.

    Strategy:
    1. Try precomputed multi-signal edges (composite_weight from entity_edges API)
    2. Fallback to co-occurrence counts from raw triples
    """
    import igraph as ig

    # Try multi-signal edges first
    api_edges = _fetch_entity_edges(space_id)
    if api_edges:
        return _build_graph_from_edges(api_edges)

    # Fallback: co-occurrence from triples
    print("[Phase 2] No precomputed edges — falling back to co-occurrence counts")
    return _build_graph_from_cooccurrence(rows)


def _build_graph_from_edges(api_edges: list[dict]):
    """Build graph from precomputed multi-signal entity edges."""
    import igraph as ig

    entities: set[str] = set()
    for e in api_edges:
        entities.add(e["entity_a_name"])
        entities.add(e["entity_b_name"])

    entity_list = sorted(entities)
    entity_to_idx = {name: i for i, name in enumerate(entity_list)}

    edges = []
    weights = []
    for e in api_edges:
        a_idx = entity_to_idx.get(e["entity_a_name"])
        b_idx = entity_to_idx.get(e["entity_b_name"])
        if a_idx is not None and b_idx is not None and a_idx != b_idx:
            edges.append((min(a_idx, b_idx), max(a_idx, b_idx)))
            weights.append(e.get("composite_weight", 1.0))

    g = ig.Graph(n=len(entity_list), edges=edges, directed=False)
    g.vs["name"] = entity_list
    g.es["weight"] = weights

    print(
        f"[Phase 2] Graph built from multi-signal edges: "
        f"{len(entity_list)} entities, {len(edges)} edges"
    )
    return g, entity_to_idx


def _build_graph_from_cooccurrence(rows: list[dict]):
    """Build graph from raw triple co-occurrence counts (original logic)."""
    import igraph as ig

    entities: set[str] = set()
    for r in rows:
        entities.add(r["s"])
        entities.add(r["o"])

    entity_list = sorted(entities)
    entity_to_idx = {e: i for i, e in enumerate(entity_list)}

    # Build edges: subject-object pairs from each triple
    edge_counts: dict[tuple[int, int], int] = {}
    for r in rows:
        s_idx = entity_to_idx[r["s"]]
        o_idx = entity_to_idx[r["o"]]
        if s_idx != o_idx:
            edge = (min(s_idx, o_idx), max(s_idx, o_idx))
            edge_counts[edge] = edge_counts.get(edge, 0) + 1

    edges = list(edge_counts.keys())
    weights = [edge_counts[e] for e in edges]

    g = ig.Graph(n=len(entity_list), edges=edges, directed=False)
    g.vs["name"] = entity_list
    g.es["weight"] = weights

    print(f"[Phase 2] Graph built from co-occurrence: {len(entity_list)} entities, {len(edges)} edges")
    return g, entity_to_idx


# ── Phase 3: Hierarchical Community Detection ────────────────────────────────
MIN_COMPONENT_FOR_LEIDEN = 5  # Only run Leiden on components with >= 5 vertices


def run_community_detection(g) -> dict[int, list[list[int]]]:
    """Detect communities using connected components + Leiden subdivision.

    Strategy adapted to sparse personal KG (many small disconnected components):
      Level 0 (fine): Connected components >= 5 vertices → Leiden(res=1.0) sub-communities.
                      Components 2-4 vertices → kept as-is.
      Level 1 (medium): Leiden(res=0.3) on large components. Small components grouped.
      Level 2 (coarse): Leiden(res=0.05) on large components. Everything else = one group.
    """
    components = g.connected_components()
    comp_groups = {}  # comp_id → list of vertex indices
    for v_idx, comp_id in enumerate(components.membership):
        comp_groups.setdefault(comp_id, []).append(v_idx)

    # Separate large vs small components
    large_comps = {
        cid: members
        for cid, members in comp_groups.items()
        if len(members) >= MIN_COMPONENT_FOR_LEIDEN
    }
    small_comps = {
        cid: members
        for cid, members in comp_groups.items()
        if 2 <= len(members) < MIN_COMPONENT_FOR_LEIDEN
    }

    print(
        f"  Components: {len(comp_groups)} total, "
        f"{len(large_comps)} large (>={MIN_COMPONENT_FOR_LEIDEN}), "
        f"{len(small_comps)} small (2-{MIN_COMPONENT_FOR_LEIDEN - 1})"
    )

    results: dict[int, list[list[int]]] = {}

    for level, resolution in RESOLUTIONS.items():
        communities: list[list[int]] = []

        # Leiden on each large component
        for _cid, members in large_comps.items():
            sub = g.subgraph(members)
            partition = sub.community_leiden(
                objective_function="modularity",
                resolution=resolution,
                weights="weight",
                n_iterations=5,
            )
            # Map back to global vertex indices
            for comm_members in partition:
                if len(comm_members) >= 2:
                    global_members = [members[i] for i in comm_members]
                    communities.append(global_members)

        # Small components: include as-is at level 0, skip at higher levels
        if level == 0:
            for members in small_comps.values():
                communities.append(members)

        results[level] = communities

        # Calculate modularity on the full graph
        # Build a membership vector for modularity calculation
        membership = [0] * g.vcount()
        for comm_idx, comm_members in enumerate(communities):
            for v in comm_members:
                membership[v] = comm_idx
        try:
            mod = g.modularity(membership, weights="weight")
        except Exception:
            mod = 0.0
        print(
            f"  Level {level} (res={resolution}): {len(communities)} communities, "
            f"modularity={mod:.4f}"
        )

    return results


# ── Phase 4: Build Community Data Structures ──────────────────────────────────
def _community_name(entity_names: list[str]) -> str:
    """Build a community name from its top 3 entities."""
    top3 = entity_names[:3]
    return " + ".join(top3)


def _map_triples_to_community(
    rows: list[dict],
    entity_to_idx: dict[str, int],
    entity_to_community: dict[int, int],
) -> dict[int, list[dict]]:
    """Map each triple to a community: use subject's community (fallback to object's)."""
    buckets: dict[int, list[dict]] = {}
    unassigned = 0

    for r in rows:
        s_idx = entity_to_idx.get(r["s"])
        o_idx = entity_to_idx.get(r["o"])

        comm_id = None
        if s_idx is not None and s_idx in entity_to_community:
            comm_id = entity_to_community[s_idx]
        elif o_idx is not None and o_idx in entity_to_community:
            comm_id = entity_to_community[o_idx]

        if comm_id is None:
            unassigned += 1
            continue

        buckets.setdefault(comm_id, []).append(r)

    if unassigned:
        print(f"  [warn] {unassigned} triples unassigned (singleton entities)")

    return buckets


def _summarize_community(
    comm_id: int,
    comm_idx: int,
    level: int,
    entity_names: list[str],
    triples: list[dict],
    parent_id: str | None = None,
) -> dict:
    """Build community summary dict from its member triples."""
    subjects = Counter(t["s"] for t in triples)
    predicates = Counter(t["p"] for t in triples)
    objects = Counter(t["o"] for t in triples)

    top_subjects = [s for s, _ in subjects.most_common(5)]
    top_predicates = [p for p, _ in predicates.most_common(5)]
    top_objects = [o for o, _ in objects.most_common(5)]

    # Community name: top 3 entities by frequency in subject position
    name_entities = top_subjects[:3] if top_subjects else entity_names[:3]
    name = _community_name(name_entities)

    contexts = [f"{t['s']} {t['p']} {t['o']}" for t in triples if t["p"] in CONTEXT_PREDICATES]
    judgments = [f"{t['s']} {t['p']} {t['o']}" for t in triples if t["p"] in JUDGMENT_PREDICATES]
    results = [f"{t['s']} {t['p']} {t['o']}" for t in triples if t["p"] in RESULT_PREDICATES]

    pattern_parts = []
    if contexts:
        pattern_parts.append("情境: " + "; ".join(contexts[:3]))
    if judgments:
        pattern_parts.append("判斷: " + "; ".join(judgments[:3]))
    if results:
        pattern_parts.append("結果: " + "; ".join(results[:3]))
    summary = (
        " → ".join(pattern_parts) if pattern_parts else f"Entities: {', '.join(entity_names[:5])}"
    )

    return {
        "community_id": f"L{level}C{comm_idx}",
        "name": name,
        "resolution_level": level,
        "size": len(triples),
        "entity_count": len(entity_names),
        "top_entities": entity_names[:10],
        "top_subjects": top_subjects,
        "top_predicates": top_predicates,
        "top_objects": top_objects,
        "triples": [
            {
                "s": t["s"],
                "p": t["p"],
                "o": t["o"],
                "id": t.get("id", ""),
                "session_id": t.get("session_id", ""),
            }
            for t in triples
        ],
        "summary": summary,
        "parent_community_id": parent_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def build_communities(
    rows: list[dict],
    g,
    leiden_results: dict[int, list[list[int]]],
    entity_to_idx: dict[str, int],
) -> list[dict]:
    """Build community data structures across all resolution levels."""
    idx_to_entity = {v: k for k, v in entity_to_idx.items()}
    all_communities: list[dict] = []

    # Track entity→community mapping per level for parent-child linking
    level_entity_maps: dict[int, dict[int, int]] = {}

    for level in sorted(leiden_results.keys()):
        communities_at_level = leiden_results[level]
        entity_to_community: dict[int, int] = {}

        for comm_idx, members in enumerate(communities_at_level):
            for member_idx in members:
                entity_to_community[member_idx] = comm_idx

        level_entity_maps[level] = entity_to_community

        # Map triples to communities
        triple_buckets = _map_triples_to_community(rows, entity_to_idx, entity_to_community)

        for comm_idx, members in enumerate(communities_at_level):
            entity_names = sorted(idx_to_entity[m] for m in members if m in idx_to_entity)
            triples = triple_buckets.get(comm_idx, [])

            # Determine parent at next coarser level
            parent_id = None
            coarser_level = level + 1
            if coarser_level in level_entity_maps and members:
                # Vote: majority entity community at coarser level
                coarser_map = level_entity_maps[coarser_level]
                coarser_votes = Counter(coarser_map[m] for m in members if m in coarser_map)
                if coarser_votes:
                    best_parent_idx = coarser_votes.most_common(1)[0][0]
                    parent_id = f"L{coarser_level}C{best_parent_idx}"

            comm_dict = _summarize_community(
                comm_id=comm_idx,
                comm_idx=comm_idx,
                level=level,
                entity_names=entity_names,
                triples=triples,
                parent_id=parent_id,
            )
            all_communities.append(comm_dict)

        print(f"[Phase 4] Level {level}: {len(communities_at_level)} communities summarized")

    return all_communities


# ── Phase 5: POST to Core API ─────────────────────────────────────────────────
def save_communities(communities: list[dict], space_id: str, dry_run: bool) -> bool:
    url = f"{CORE_API}/api/memvault/kg/communities/regenerate"
    payload = {
        "space_id": space_id,
        "communities": communities,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "n_communities": len(communities),
        "resolution_levels": list(RESOLUTIONS.keys()),
    }

    if dry_run:
        print(f"\n[Phase 5] DRY RUN — would POST {len(communities)} communities to {url}")
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:1000])
        return True

    print(f"\n[Phase 5] POSTing {len(communities)} communities to Core API ...")
    result = http_post(url, payload, params={"space_id": space_id})
    if "error" in result:
        print(f"[Phase 5] Core API save failed: {result}", file=sys.stderr)
        return False

    print("[Phase 5] Communities saved to Core API")
    return True


def print_report(rows: list[dict], communities: list[dict]) -> None:
    print("\n" + "=" * 60)
    print("  Memvault — Leiden Community Detection Pipeline Report")
    print("=" * 60)
    print(f"  Total triples     : {len(rows)}")
    print(f"  Total communities : {len(communities)}")
    for level in sorted(RESOLUTIONS.keys()):
        level_comms = [c for c in communities if c["resolution_level"] == level]
        res = RESOLUTIONS[level]
        print(f"  Level {level} (res={res:4.2f})  : {len(level_comms)} communities")
    print("=" * 60)

    # Show top 5 largest communities at medium level (level 1)
    medium = sorted(
        [c for c in communities if c["resolution_level"] == 1],
        key=lambda c: c["size"],
        reverse=True,
    )[:5]
    if medium:
        print("\n  Top communities at Level 1 (medium):")
        for c in medium:
            name = c["name"]
            print(
                f"  [{c['community_id']}] {name}  (size={c['size']}, entities={c['entity_count']})"
            )
            preds = ", ".join(c["top_predicates"][:3])
            print(f"    Predicates : {preds}")
            summary = c["summary"]
            print(f"    Summary    : {summary[:100]}{'...' if len(summary) > 100 else ''}")
    print("\n" + "=" * 60)


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Memvault community pipeline — Leiden graph community detection"
    )
    parser.add_argument("--space-id", default=os.environ.get("MEMVAULT_SPACE_ID", "default"))
    parser.add_argument("--dry-run", action="store_true", help="Print results without saving")
    args = parser.parse_args()

    print("Memvault — community_pipeline.py")
    print(f"Core API : {CORE_API}")
    print(f"Space ID : {args.space_id}\n")

    # Ensure igraph is available
    ensure_igraph()

    # Phase 1
    rows = fetch_triples(args.space_id)
    if len(rows) < 5:
        print(f"[skip] Only {len(rows)} triples — need at least 5 to detect communities.")
        sys.exit(0)

    # Phase 2
    print("\n[Phase 2] Building entity graph (multi-signal preferred) ...")
    g, entity_to_idx = build_entity_graph(rows, space_id=args.space_id)

    if g.ecount() == 0:
        print("[skip] Graph has no edges — cannot run community detection.")
        sys.exit(0)

    # Phase 3
    print("\n[Phase 3] Running Leiden community detection at 3 resolution levels ...")
    leiden_results = run_community_detection(g)

    # Phase 4
    print("\n[Phase 4] Building community data structures ...")
    communities = build_communities(rows, g, leiden_results, entity_to_idx)
    print(f"[Phase 4] Total: {len(communities)} communities across {len(RESOLUTIONS)} levels")

    # Report + Phase 5
    print_report(rows, communities)
    ok = save_communities(communities, args.space_id, args.dry_run)
    if not ok:
        print("\n[warn] Failed to save communities to Core API", file=sys.stderr)
        sys.exit(1)

    print(f"\nDone. {len(communities)} communities saved.")


if __name__ == "__main__":
    main()
