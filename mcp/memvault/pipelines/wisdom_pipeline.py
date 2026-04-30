#!/usr/bin/env python3
"""wisdom_pipeline.py — Memvault V2 Knowledge Graph: Wisdom Node Pipeline

Fetches clusters from Core API, detects cross-cluster bridge entities,
calls Gemini Flash to synthesize wisdom nodes, and saves results.

Usage:
    python3 wisdom_pipeline.py [--space-id default] [--max-bridges 15] [--dry-run]
    uv run wisdom_pipeline.py
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime

# ── Configuration ──────────────────────────────────────────────────────────────
CORE_API = os.environ.get("CORE_API_URL", "http://localhost:10000")
GEMINI_CMD = "gemini"
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")
MIN_CLUSTERS_FOR_BRIDGE = 2  # entity must appear in ≥2 clusters
MIN_TRIPLES_PER_BRIDGE = 4  # need enough triples to synthesize
DEFAULT_MAX_BRIDGES = 15  # max Gemini calls per run

WISDOM_PROMPT = """You are a knowledge distillation expert. Given triples from MULTIPLE clusters
that share a common entity/theme, synthesize a single WISDOM NODE — a high-level heuristic
or rule-of-thumb that spans across these clusters.

This should be an insight that:
- Can't be easily found on Google/StackOverflow
- Comes from real-world experience across multiple domains
- Is actionable and concise (1-3 sentences)
- Follows the pattern: "When [context], [judgment], because [evidence from multiple clusters]"

Output ONLY valid JSON:
{
  "wisdom": "The heuristic in 1-3 sentences (繁體中文 preferred)",
  "confidence": "HIGH|MEDIUM|LOW",
  "bridge_entity": "The entity that connects the clusters",
  "cluster_ids": ["C0", "C2"],
  "evidence_count": 8,
  "tags": ["tag1", "tag2"]
}

Here are the cross-cluster triples:
"""


# ── HTTP helpers ───────────────────────────────────────────────────────────────
_INTERNAL_KEY = os.environ.get("CORE_INTERNAL_API_KEY", "")


def _internal_headers(extra: dict | None = None) -> dict:
    h = {"Accept": "application/json"}
    if _INTERNAL_KEY:
        h["x-internal-key"] = _INTERNAL_KEY
    if extra:
        h.update(extra)
    return h


def http_get(url: str, params: dict | None = None) -> dict:
    if params:
        from urllib.parse import urlencode

        url = f"{url}?{urlencode(params)}"
    req = urllib.request.Request(url, headers=_internal_headers())
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
        from urllib.parse import urlencode

        url = f"{url}?{urlencode(params)}"
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers=_internal_headers({"Content-Type": "application/json"}),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode("utf-8", errors="replace")[:200]
        print(f"[error] POST {url} → HTTP {e.code}: {body_txt}", file=sys.stderr)
        return {"error": e.code}
    except urllib.error.URLError as e:
        print(f"[error] POST {url} → {e}", file=sys.stderr)
        return {"error": str(e)}


# ── Phase 1: Fetch Clusters (with detail triples) from Core API ──────────────
def fetch_clusters(space_id: str) -> dict:
    url = f"{CORE_API}/api/memvault/kg/clusters"
    print(f"[Phase 1] Fetching clusters from {url} (space={space_id}) ...")
    data = http_get(url, params={"space_id": space_id})

    # Normalise: may be list or {"clusters": [...], ...}
    if isinstance(data, list):
        cluster_list = data
    else:
        cluster_list = data.get("clusters", data.get("items", []))

    # Fetch detail (including triples) for each cluster
    clusters = []
    for c in cluster_list:
        cid = c.get("id", "")
        if not cid:
            clusters.append(c)
            continue
        detail_url = f"{CORE_API}/api/memvault/kg/clusters/{cid}"
        try:
            detail = http_get(detail_url)
            clusters.append(detail)
        except SystemExit:
            # http_get calls sys.exit on error — fallback to summary
            clusters.append(c)

    total_triples = sum(c.get("size", len(c.get("triples", []))) for c in clusters)
    print(f"[Phase 1] Loaded {len(clusters)} clusters, ~{total_triples} triples")
    return {"clusters": clusters, "n_clusters": len(clusters), "total_triples": total_triples}


# ── Phase 2: Find Cross-Cluster Bridge Entities ────────────────────────────────
def find_bridges(data: dict) -> list[dict]:
    """Entities (subjects/objects) that appear in multiple clusters."""
    entity_clusters: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))

    for cluster in data["clusters"]:
        cid = cluster.get("cluster_id") or cluster.get("id", "?")
        for triple in cluster.get("triples", []):
            s = (triple.get("s") or triple.get("subject") or "").strip()
            o = (triple.get("o") or triple.get("object") or "").strip()
            p = (triple.get("p") or triple.get("predicate") or "").strip()
            t = {"s": s, "p": p, "o": o}
            if s:
                entity_clusters[s][cid].append(t)
            if o:
                entity_clusters[o][cid].append(t)

    bridges = []
    for entity, cluster_map in entity_clusters.items():
        if len(cluster_map) >= MIN_CLUSTERS_FOR_BRIDGE:
            total = sum(len(ts) for ts in cluster_map.values())
            if total >= MIN_TRIPLES_PER_BRIDGE:
                bridges.append(
                    {
                        "entity": entity,
                        "cluster_ids": sorted(cluster_map.keys()),
                        "n_clusters": len(cluster_map),
                        "n_triples": total,
                        "triples_by_cluster": {
                            cid: [{"s": t["s"], "p": t["p"], "o": t["o"]} for t in ts]
                            for cid, ts in cluster_map.items()
                        },
                    }
                )

    bridges.sort(key=lambda b: (b["n_clusters"], b["n_triples"]), reverse=True)
    return bridges


# ── Phase 3: Synthesize Wisdom via Gemini Flash ────────────────────────────────
def call_gemini(bridge: dict) -> dict | None:
    triples_text = []
    for cid, ts in bridge["triples_by_cluster"].items():
        triples_text.append(f"\n--- Cluster {cid} ---")
        for t in ts[:8]:
            triples_text.append(f"  ({t['s']}, {t['p']}, {t['o']})")

    prompt_content = WISDOM_PROMPT + "\n".join(triples_text)
    prompt_content += f"\n\nBridge entity: {bridge['entity']}"
    prompt_content += f"\nClusters involved: {', '.join(bridge['cluster_ids'])}"

    try:
        result = subprocess.run(
            [
                GEMINI_CMD,
                "-m",
                GEMINI_MODEL,
                "-p",
                "Synthesize a wisdom node from cross-cluster triples. Output ONLY valid JSON.",
            ],
            input=prompt_content,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            return None

        raw = result.stdout.strip()
        lines = [
            ln
            for ln in raw.splitlines()
            if not ln.startswith("```")
            and not ln.startswith("Created execution plan")
            and not ln.startswith("Expanding hook")
            and not ln.startswith("Hook execution")
        ]
        clean = "\n".join(lines).strip()
        if not clean:
            return None
        return json.loads(clean)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
        print(f"  [warn] Gemini call failed for '{bridge['entity']}': {e}", file=sys.stderr)
        return None


# ── Phase 4: Save Wisdom to Core API ──────────────────────────────────────────
def save_wisdom(wisdom_nodes: list[dict], space_id: str, dry_run: bool) -> bool:
    url = f"{CORE_API}/api/memvault/kg/wisdom/regenerate"
    payload = {
        "wisdom_nodes": wisdom_nodes,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }

    if dry_run:
        print(f"\n[Phase 4] DRY RUN — would POST {len(wisdom_nodes)} wisdom nodes to {url}")
        for w in wisdom_nodes:
            print(f"  [{w.get('confidence', '?')}] {w.get('bridge_entity', '?')[:50]}")
            print(f"    {w.get('wisdom', '')[:120]}")
        return True

    print(f"\n[Phase 4] POSTing {len(wisdom_nodes)} wisdom nodes to Core API ...")
    result = http_post(url, payload, params={"space_id": space_id})
    if "error" in result:
        print(f"[Phase 4] Core API save failed: {result}", file=sys.stderr)
        return False

    print("[Phase 4] Wisdom nodes saved")
    return True


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Memvault wisdom pipeline — cross-cluster bridge synthesis"
    )
    parser.add_argument("--space-id", default=os.environ.get("MEMVAULT_SPACE_ID", "default"))
    parser.add_argument(
        "--max-bridges",
        type=int,
        default=DEFAULT_MAX_BRIDGES,
        help="Max Gemini calls (default: 15)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Skip writing to Core API")
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Global timeout in seconds (default: 600 = 10 min)",
    )
    args = parser.parse_args()
    _deadline = time.monotonic() + args.timeout

    print("Memvault — wisdom_pipeline.py")
    print(f"Core API : {CORE_API}")
    print(f"Space ID : {args.space_id}\n")

    # Phase 1
    data = fetch_clusters(args.space_id)
    if data["n_clusters"] < 2:
        print(f"[skip] Only {data['n_clusters']} cluster(s) — need at least 2 for bridges.")
        sys.exit(0)

    # Phase 2
    bridges = find_bridges(data)
    print(f"[Phase 2] Found {len(bridges)} cross-cluster bridges")
    for b in bridges[:10]:
        print(f"  {b['entity'][:50]:50s}  clusters={b['n_clusters']}  triples={b['n_triples']}")

    top_bridges = bridges[: args.max_bridges]
    print(
        f"\n[Phase 3] Synthesizing wisdom from top {len(top_bridges)} bridges via Gemini Flash..."
    )

    # Phase 3
    wisdom_nodes = []
    for i, bridge in enumerate(top_bridges):
        if time.monotonic() > _deadline:
            remaining = len(top_bridges) - i
            print(f"\n  [TIMEOUT] {args.timeout}s reached, {remaining} bridges skipped")
            break
        label = bridge["entity"][:40]
        print(f"  [{i + 1}/{len(top_bridges)}] {label}...", end=" ", flush=True)
        result = call_gemini(bridge)
        if result:
            result["bridge_entity"] = bridge["entity"]
            result["cluster_ids"] = bridge["cluster_ids"]
            result["evidence_count"] = bridge["n_triples"]
            wisdom_nodes.append(result)
            print("OK")
        else:
            print("SKIP")

    # Phase 4
    ok = save_wisdom(wisdom_nodes, args.space_id, args.dry_run)

    # Report
    print(f"\n{'=' * 60}")
    print("  Memvault — Wisdom Pipeline Report")
    print(f"{'=' * 60}")
    print(f"  Bridges found   : {len(bridges)}")
    print(f"  Processed       : {len(top_bridges)}")
    print(f"  Wisdom generated: {len(wisdom_nodes)}")
    print(f"{'=' * 60}")
    for w in wisdom_nodes:
        conf = w.get("confidence", "?")
        entity = w.get("bridge_entity", "?")[:50]
        clusters = ", ".join(w.get("cluster_ids", []))
        wisdom_text = w.get("wisdom", "")
        print(f"\n  [{conf}] {entity}")
        print(f"    Clusters: {clusters}")
        print(f"    Wisdom  : {wisdom_text[:120]}{'...' if len(wisdom_text) > 120 else ''}")
    print(f"\n{'=' * 60}")

    if not ok:
        sys.exit(1)
    print("Done.")


if __name__ == "__main__":
    main()
