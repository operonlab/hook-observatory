#!/usr/bin/env python3
"""cluster_pipeline.py — Memvault V2 Knowledge Graph: GMM Clustering Pipeline

Fetches all triples from Core API, embeds via Ollama nomic-embed-text,
runs Gaussian Mixture Model clustering with BIC-optimal k,
and POSTs cluster results back to Core API.

Usage:
    python3 cluster_pipeline.py [--space-id default] [--dry-run]
    uv run cluster_pipeline.py

Dependencies: scikit-learn, numpy, httpx (auto-installed if missing via uv)
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

# ── Configuration ──────────────────────────────────────────────────────────────
CORE_API = os.environ.get("CORE_API_URL", "http://localhost:8801")
OLLAMA_URL = "http://localhost:11434/api/embed"
OLLAMA_MODEL = "nomic-embed-text"
EMBED_CHUNK_SIZE = 100
BIC_RANGE_MIN = 3
BIC_RANGE_MAX = 25
MAX_TRIPLES_PER_FETCH = 5000


# ── HTTP helpers (stdlib only, no external deps) ───────────────────────────────
def http_get(url: str, params: dict | None = None) -> dict:
    if params:
        from urllib.parse import urlencode
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
        from urllib.parse import urlencode
        url = f"{url}?{urlencode(params)}"
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
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
    page_size = 100  # API max
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
                rows.append({
                    "id": item.get("id", ""),
                    "s": s, "p": p, "o": o,
                    "text": f"{s} {p} {o}",
                    "session_id": item.get("session_id", ""),
                    "topic": item.get("topic", ""),
                    "tags": item.get("tags", []),
                })

        if len(items) < page_size:
            break
        if len(rows) >= MAX_TRIPLES_PER_FETCH:
            break
        page += 1

    print(f"[Phase 1] Loaded {len(rows)} triples (API total: {total})")
    return rows


# ── Phase 2: Embed with Ollama ─────────────────────────────────────────────────
def ollama_embed_batch(texts: list[str]) -> list[list[float]]:
    payload = json.dumps({"model": OLLAMA_MODEL, "input": texts}).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("embeddings", [])
    except urllib.error.URLError as e:
        print(f"[error] Ollama connection failed: {e}", file=sys.stderr)
        print("[error] Is Ollama running? Try: ollama serve", file=sys.stderr)
        sys.exit(1)


def embed_triples(rows: list[dict]) -> list[list[float]]:
    texts = [r["text"] for r in rows]
    embeddings: list[list[float]] = []

    if len(texts) <= EMBED_CHUNK_SIZE * 5:
        print(f"[Phase 2] Embedding {len(texts)} triples in one batch...")
        embeddings = ollama_embed_batch(texts)
    else:
        total_chunks = (len(texts) + EMBED_CHUNK_SIZE - 1) // EMBED_CHUNK_SIZE
        print(f"[Phase 2] Embedding {len(texts)} triples in {total_chunks} chunks...")
        for i in range(0, len(texts), EMBED_CHUNK_SIZE):
            chunk = texts[i: i + EMBED_CHUNK_SIZE]
            embeddings.extend(ollama_embed_batch(chunk))
            print(f"  chunk {i // EMBED_CHUNK_SIZE + 1}/{total_chunks} done", end="\r")
        print()

    if len(embeddings) != len(texts):
        print(f"[error] Expected {len(texts)} embeddings, got {len(embeddings)}", file=sys.stderr)
        sys.exit(1)

    dim = len(embeddings[0]) if embeddings else 0
    print(f"[Phase 2] Embeddings ready: {len(embeddings)} vectors, dim={dim}")
    return embeddings


# ── Phase 3: GMM Clustering ────────────────────────────────────────────────────
def ensure_sklearn():
    try:
        import sklearn  # noqa: F401
    except ImportError:
        print("[Phase 3] scikit-learn not found — installing via uv...")
        result = subprocess.run(
            ["/opt/homebrew/bin/uv", "pip", "install", "scikit-learn", "--python", sys.executable],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"[error] Failed to install scikit-learn:\n{result.stderr}", file=sys.stderr)
            sys.exit(1)
        print("[Phase 3] scikit-learn installed.")


def run_gmm(embeddings: list[list[float]], n_triples: int) -> tuple[int, list[int]]:
    ensure_sklearn()
    import numpy as np
    from sklearn.decomposition import PCA
    from sklearn.mixture import GaussianMixture

    X = np.array(embeddings)
    orig_dim = X.shape[1]

    # PCA: reduce 768-dim to ~50 components (retain ~95% variance)
    n_components_pca = min(50, X.shape[0] // 5, orig_dim)
    pca = PCA(n_components=n_components_pca, random_state=42)
    X_pca = pca.fit_transform(X)
    variance_retained = pca.explained_variance_ratio_.sum()
    print(f"[Phase 3] PCA: {orig_dim}d → {n_components_pca}d (variance retained: {variance_retained:.1%})")

    max_k = min(BIC_RANGE_MAX, n_triples // 10)
    k_range = range(BIC_RANGE_MIN, max(BIC_RANGE_MIN + 1, max_k + 1))

    print(f"[Phase 3] BIC search over k={list(k_range)} (diag covariance)...")
    best_bic = float("inf")
    best_k = BIC_RANGE_MIN
    bic_scores: dict[int, float] = {}

    for k in k_range:
        gmm = GaussianMixture(n_components=k, covariance_type="diag",
                              random_state=42, max_iter=300, n_init=3)
        gmm.fit(X_pca)
        bic = gmm.bic(X_pca)
        bic_scores[k] = round(bic, 2)
        if bic < best_bic:
            best_bic = bic
            best_k = k
        print(f"  k={k:2d}  BIC={bic:>12.2f}  {'*' if bic == best_bic else ''}")

    print(f"[Phase 3] Optimal k={best_k} (BIC={best_bic:.2f})")

    gmm_final = GaussianMixture(n_components=best_k, covariance_type="diag",
                                random_state=42, max_iter=300, n_init=3)
    gmm_final.fit(X_pca)
    labels = gmm_final.predict(X_pca).tolist()
    return best_k, labels


# ── Phase 4: Cluster Summaries ─────────────────────────────────────────────────
JUDGMENT_PREDICATES = {"should", "should_NOT", "chosen_over"}
RESULT_PREDICATES = {"improves", "fixes", "enables", "prevents"}
CONTEXT_PREDICATES = {"causes", "requires", "depends_on", "uses"}


def summarize_cluster(cluster_triples: list[dict], cluster_id: int) -> dict:
    subjects = Counter(t["s"] for t in cluster_triples)
    predicates = Counter(t["p"] for t in cluster_triples)
    objects = Counter(t["o"] for t in cluster_triples)

    top_subjects = [s for s, _ in subjects.most_common(3)]
    top_predicates = [p for p, _ in predicates.most_common(3)]
    top_objects = [o for o, _ in objects.most_common(3)]

    name_parts = top_subjects[:2] if top_subjects else [f"Cluster {cluster_id}"]
    name = " + ".join(name_parts)

    contexts = [f"{t['s']} {t['p']} {t['o']}"
                for t in cluster_triples if t["p"] in CONTEXT_PREDICATES]
    judgments = [f"{t['s']} {t['p']} {t['o']}"
                 for t in cluster_triples if t["p"] in JUDGMENT_PREDICATES]
    results = [f"{t['s']} {t['p']} {t['o']}"
               for t in cluster_triples if t["p"] in RESULT_PREDICATES]

    pattern_parts = []
    if contexts:
        pattern_parts.append("情境: " + "; ".join(contexts[:3]))
    if judgments:
        pattern_parts.append("判斷: " + "; ".join(judgments[:3]))
    if results:
        pattern_parts.append("結果: " + "; ".join(results[:3]))
    summary = " → ".join(pattern_parts) if pattern_parts else f"Triples about: {', '.join(top_subjects)}"

    return {
        "cluster_id": f"C{cluster_id}",
        "name": name,
        "size": len(cluster_triples),
        "top_subjects": top_subjects,
        "top_predicates": top_predicates,
        "top_objects": top_objects,
        "triples": [
            {"s": t["s"], "p": t["p"], "o": t["o"],
             "id": t.get("id", ""), "session_id": t.get("session_id", "")}
            for t in cluster_triples
        ],
        "summary": summary,
        "verdict": "UNVERIFIED",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def build_clusters(rows: list[dict], n_clusters: int, labels: list[int]) -> list[dict]:
    buckets: dict[int, list[dict]] = {}
    for row, label in zip(rows, labels):
        buckets.setdefault(label, []).append(row)

    clusters = [summarize_cluster(buckets[cid], cid) for cid in sorted(buckets.keys())]
    clusters.sort(key=lambda c: c["size"], reverse=True)
    return clusters


# ── Phase 5: POST to Core API ──────────────────────────────────────────────────
def save_clusters(clusters: list[dict], space_id: str, dry_run: bool) -> bool:
    url = f"{CORE_API}/api/memvault/kg/clusters/regenerate"
    payload = {
        "space_id": space_id,
        "clusters": clusters,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "n_clusters": len(clusters),
    }

    if dry_run:
        print(f"\n[Phase 5] DRY RUN — would POST {len(clusters)} clusters to {url}")
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:800])
        return True

    print(f"\n[Phase 5] POSTing {len(clusters)} clusters to Core API ...")
    result = http_post(url, payload, params={"space_id": space_id})
    if "error" in result:
        print(f"[Phase 5] Core API save failed: {result}", file=sys.stderr)
        return False

    print("[Phase 5] Clusters saved to Core API")
    return True


def print_report(rows: list[dict], n_clusters: int, clusters: list[dict]) -> None:
    print("\n" + "=" * 60)
    print("  Memvault — GMM Cluster Pipeline Report")
    print("=" * 60)
    print(f"  Total triples : {len(rows)}")
    print(f"  Clusters found: {n_clusters}")
    print("=" * 60)
    for c in clusters:
        print(f"\n  [{c['cluster_id']}] {c['name']}  (size={c['size']})")
        print(f"    Predicates : {', '.join(c['top_predicates'])}")
        print(f"    Subjects   : {', '.join(c['top_subjects'])}")
        summary = c["summary"]
        print(f"    Summary    : {summary[:100]}{'...' if len(summary) > 100 else ''}")
    print("\n" + "=" * 60)


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Memvault cluster pipeline — GMM clustering via Core API")
    parser.add_argument("--space-id", default=os.environ.get("MEMVAULT_SPACE_ID", "default"))
    parser.add_argument("--dry-run", action="store_true", help="Print results without saving")
    args = parser.parse_args()

    print("Memvault — cluster_pipeline.py")
    print(f"Core API : {CORE_API}")
    print(f"Space ID : {args.space_id}\n")

    # Phase 1
    rows = fetch_triples(args.space_id)
    if len(rows) < 5:
        print(f"[skip] Only {len(rows)} triples — need at least 5 to cluster.")
        sys.exit(0)

    # Phase 2
    embeddings = embed_triples(rows)

    # Phase 3
    n_clusters, labels = run_gmm(embeddings, len(rows))

    # Phase 4
    clusters = build_clusters(rows, n_clusters, labels)
    print(f"[Phase 4] Generated summaries for {len(clusters)} clusters")

    # Phase 5
    print_report(rows, n_clusters, clusters)
    ok = save_clusters(clusters, args.space_id, args.dry_run)
    if not ok:
        print("\n[warn] Failed to save clusters to Core API", file=sys.stderr)
        sys.exit(1)

    print(f"\nDone. {len(clusters)} clusters saved.")


if __name__ == "__main__":
    main()
