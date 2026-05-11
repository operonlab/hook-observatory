#!/usr/bin/env python3
"""community_summary_pipeline.py — Memvault V2 Knowledge Graph: LLM Community Summarization

Fetches medium-resolution communities from Core API, generates LLM summaries
for each via DeepSeek V3, and POSTs results back to Core API.

Usage:
    python3 community_summary_pipeline.py [--space-id default] [--dry-run] [--level 1]
    ~/.local/bin/python3 community_summary_pipeline.py

Environment:
    DEEPSEEK_API_KEY  — required for LLM summarization
    CORE_API_URL      — defaults to http://localhost:10000
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from urllib.parse import urlencode

# ── Configuration ──────────────────────────────────────────────────────────────
CORE_API = os.environ.get("CORE_API_URL", "http://localhost:10000")
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

# ── Evidence Signal Weighting (Phase B — graphify-cannibalized 2026-05-11) ────
# Feature flag: set MEMVAULT_USE_EVIDENCE_SIGNAL_WEIGHTS=0 to disable
_USE_EVIDENCE_SIGNAL_WEIGHTS: bool = (
    os.environ.get("MEMVAULT_USE_EVIDENCE_SIGNAL_WEIGHTS", "1") != "0"
)

# Weight multipliers per evidence_signal tier.
# extracted = direct evidence from source text (highest weight)
# inferred  = LLM/semantic inference from context
# ambiguous = low-certainty, multi-source conflict
EVIDENCE_SIGNAL_WEIGHT: dict[str, float] = {
    "extracted": 1.0,
    "inferred": 0.7,
    "ambiguous": 0.3,
}

# Retry settings for LLM calls
LLM_RETRY_COUNT = 3
LLM_RETRY_DELAY = 2.0  # seconds between retries

# Self-imposed runtime limit (seconds). When hit, save partial results and exit.
MAX_RUNTIME = 600  # 10 minutes

# Max triples to include in the LLM prompt per community
MAX_TRIPLES_IN_PROMPT = 40

SUMMARY_PROMPT = (
    "以下是屬於同一知識社群的三元組。"
    "請用繁體中文總結這個社群的主題（50-100字），"
    "並列出 2-4 個核心發現。"
    '輸出 JSON: {"summary": "...", "key_findings": ["..."]}'
)


# ── HTTP helpers (stdlib only) ─────────────────────────────────────────────────
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
        url = f"{url}?{urlencode(params)}"
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers=_internal_headers({"Content-Type": "application/json"}),
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


def http_post_auth(url: str, body: dict, api_key: str) -> dict:
    """POST with Bearer token auth (for external APIs like DeepSeek)."""
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"HTTP {e.code}: {body_txt}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"URLError: {e}")


# ── Phase 1: Fetch Communities from Core API ──────────────────────────────────
def fetch_communities(
    space_id: str, resolution_level: int, max_items: int | None = None
) -> list[dict]:
    """Fetch communities with optional cap to prevent fetching all 4000+ items.

    max_items: stop once we've accumulated this many. Each page is ~2MB JSON;
    fetching all pages without a cap puts ~100MB raw + ~800MB-3GB Python dict
    overhead into RAM, easily blowing the 2GB cronicle memory limit.
    """
    url = f"{CORE_API}/api/memvault/kg/communities"
    page_size = 100
    page = 1
    communities: list[dict] = []
    total = None

    print(
        f"[Phase 1] Fetching communities from {url} "
        f"(space={space_id}, level={resolution_level}, max_items={max_items}) ..."
    )

    while True:
        params = {
            "space_id": space_id,
            "resolution_level": resolution_level,
            "page_size": page_size,
            "page": page,
        }
        data = http_get(url, params)

        items = data.get("items", []) if isinstance(data, dict) else data
        if total is None:
            total = data.get("total", 0) if isinstance(data, dict) else len(items)

        if not items:
            break

        communities.extend(items)

        if max_items is not None and len(communities) >= max_items:
            communities = communities[:max_items]
            break

        if len(items) < page_size:
            break
        page += 1

    print(f"[Phase 1] Loaded {len(communities)} communities (API total: {total})")
    return communities


# ── Phase 2: Fetch Member Triples per Community ───────────────────────────────
def fetch_community_triples(community_id: str, space_id: str) -> list[dict]:
    """Fetch triples belonging to a specific community."""
    url = f"{CORE_API}/api/memvault/kg/communities/{community_id}/triples"
    params = {"space_id": space_id, "page_size": MAX_TRIPLES_IN_PROMPT}
    data = http_get(url, params)
    items = data.get("items", []) if isinstance(data, dict) else data
    return items


def _triples_from_community_record(community: dict) -> list[dict]:
    """Extract triples embedded in the community record (if already present)."""
    return community.get("triples", [])


# ── Phase 3: Generate Summary via DeepSeek V3 ────────────────────────────────


def _apply_evidence_weight(base_weight: float, triple: dict) -> float:
    """Apply evidence_signal multiplier to a base weight.

    Feature-flagged: returns base_weight unchanged if
    MEMVAULT_USE_EVIDENCE_SIGNAL_WEIGHTS=0.

    Returns final_weight = base_weight * multiplier.
    """
    if not _USE_EVIDENCE_SIGNAL_WEIGHTS:
        return base_weight
    signal = triple.get("evidence_signal", "extracted") or "extracted"
    multiplier = EVIDENCE_SIGNAL_WEIGHT.get(signal, 1.0)
    return base_weight * multiplier


def _build_triple_text(triples: list[dict]) -> str:
    """Build LLM prompt text from triples, sorted by evidence weight (desc).

    Triples with higher evidence signal quality appear first in the prompt,
    giving the LLM stronger grounding for its summary.
    Logs a sample of weight adjustments on first call for shadow-log comparison.
    """
    if not triples:
        return ""

    # Score triples by evidence weight for ordering
    scored: list[tuple[float, dict]] = []
    _log_samples: list[str] = []
    _sampled = 0

    for t in triples:
        base = 1.0
        final = _apply_evidence_weight(base, t)
        scored.append((final, t))
        if _sampled < 3 and _USE_EVIDENCE_SIGNAL_WEIGHTS:
            signal = t.get("evidence_signal", "extracted")
            s = t.get("s", t.get("subject", ""))[:20]
            p = t.get("p", t.get("predicate", ""))[:12]
            _log_samples.append(f"{s}→{p} signal={signal} w={base:.2f}→{final:.2f}")
            _sampled += 1

    if _log_samples:
        print(f"[evidence-weight sample] {'; '.join(_log_samples)}")

    # Sort descending by weight (highest confidence evidence first)
    scored.sort(key=lambda x: x[0], reverse=True)

    lines = []
    for _weight, t in scored[:MAX_TRIPLES_IN_PROMPT]:
        s = t.get("s", t.get("subject", ""))
        p = t.get("p", t.get("predicate", ""))
        o = t.get("o", t.get("object", ""))
        if s and p and o:
            lines.append(f"- {s} → {p} → {o}")
    return "\n".join(lines)


def _call_deepseek(triples_text: str, api_key: str) -> dict:
    """Call DeepSeek V3 API to summarize a community's triples."""
    user_content = f"{triples_text}\n\n{SUMMARY_PROMPT}"
    body = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "你是一個知識圖譜分析助手，專門提取三元組中的主題模式。",
            },
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.3,
        "max_tokens": 512,
        "response_format": {"type": "json_object"},
    }

    for attempt in range(1, LLM_RETRY_COUNT + 1):
        try:
            resp = http_post_auth(DEEPSEEK_API_URL, body, api_key)
            content = resp["choices"][0]["message"]["content"]
            return json.loads(content)
        except (KeyError, json.JSONDecodeError) as e:
            if attempt == LLM_RETRY_COUNT:
                raise RuntimeError(f"Failed to parse DeepSeek response: {e}")
            time.sleep(LLM_RETRY_DELAY)
        except RuntimeError as e:
            if attempt == LLM_RETRY_COUNT:
                raise
            print(
                f"  [warn] DeepSeek attempt {attempt} failed: {e} — retrying ...", file=sys.stderr
            )
            time.sleep(LLM_RETRY_DELAY * attempt)


def _fetch_existing_summaries(space_id: str) -> dict[str, dict]:
    """Fetch all existing summaries, keyed by community_id."""
    url = f"{CORE_API}/api/memvault/kg/summaries"
    page_size = 200
    page = 1
    result: dict[str, dict] = {}

    while True:
        params = {"space_id": space_id, "page_size": page_size, "page": page}
        try:
            data = http_get(url, params)
        except SystemExit:
            # http_get calls sys.exit on error — catch and return empty
            return {}
        items = data.get("items", []) if isinstance(data, dict) else data
        if not items:
            break
        for s in items:
            cid = s.get("community_id")
            if cid:
                result[cid] = s
        if len(items) < page_size:
            break
        page += 1

    return result


def _needs_regeneration(community: dict, existing_summary: dict) -> bool:
    """Check if community content changed since last summary generation.

    Two signals:
    1. Timestamp: community updated after summary was created
    2. Size: triple count mismatch (community grew or shrank)
    """
    # Timestamp comparison (ISO 8601 strings are lexicographically comparable)
    comm_updated = community.get("updated_at", "")
    summ_created = existing_summary.get("created_at", "")
    if comm_updated and summ_created and comm_updated > summ_created:
        return True

    # Size mismatch
    comm_size = community.get("size", -1)
    summ_evidence = existing_summary.get("evidence_count", -2)
    if comm_size != summ_evidence:
        return True

    return False


def generate_summaries(
    communities: list[dict],
    space_id: str,
    api_key: str,
    dry_run: bool,
    *,
    max_runtime: int = MAX_RUNTIME,
    force: bool = False,
) -> list[dict]:
    """Generate LLM summaries for each community.

    Skips communities whose content hasn't changed since last summary,
    unless force=True.
    """
    summaries: list[dict] = []
    total = len(communities)
    t0 = time.monotonic()

    # Fetch existing summaries for skip-if-unchanged logic
    existing_map: dict[str, dict] = {}
    if not force and not dry_run:
        print("[Phase 2.5] Fetching existing summaries for delta check ...")
        existing_map = _fetch_existing_summaries(space_id)
        print(f"[Phase 2.5] Found {len(existing_map)} existing summaries")

    skipped_unchanged = 0

    print(f"\n[Phase 3] Generating LLM summaries for {total} communities (max {max_runtime}s) ...")

    for idx, community in enumerate(communities, 1):
        elapsed = time.monotonic() - t0
        if elapsed > max_runtime:
            print(
                f"\n[Phase 3] TIMEOUT after {elapsed:.0f}s — "
                f"saving {len(summaries)}/{total} partial results"
            )
            break
        comm_id = community.get("community_id", community.get("id", f"comm_{idx}"))
        name = community.get("name", comm_id)

        # Skip if unchanged
        if comm_id in existing_map and not _needs_regeneration(community, existing_map[comm_id]):
            skipped_unchanged += 1
            continue

        print(f"  [{idx}/{total}] {comm_id}: {name[:50]}", end=" ... ", flush=True)

        # Use embedded triples first; fall back to community metadata
        triples = _triples_from_community_record(community)
        if not triples:
            # Build pseudo-triples from community metadata
            top_entities = community.get("top_entities", [])
            top_preds = community.get("top_predicates", [])
            rule_summary = community.get("summary", "")
            if top_entities or rule_summary:
                triples = [
                    {"s": e, "p": p, "o": ""} for e in top_entities[:5] for p in top_preds[:3]
                ]
                if rule_summary:
                    triples.insert(0, {"s": name, "p": "description", "o": rule_summary})

        evidence = community.get("size", len(triples))

        if not triples:
            print("(skip: no triples)")
            summaries.append(
                {
                    "community_id": comm_id,
                    "summary": "(無三元組，跳過摘要)",
                    "key_findings": [],
                    "evidence_count": 0,
                    "generated_at": datetime.now().isoformat(timespec="seconds"),
                    "skipped": True,
                }
            )
            continue

        triples_text = _build_triple_text(triples)

        if dry_run:
            print("(dry-run)")
            summaries.append(
                {
                    "community_id": comm_id,
                    "summary": f"[DRY RUN] {len(triples)} triples in community '{name}'",
                    "key_findings": ["(dry run — no LLM called)"],
                    "evidence_count": evidence,
                    "generated_at": datetime.now().isoformat(timespec="seconds"),
                    "skipped": False,
                }
            )
            continue

        try:
            result = _call_deepseek(triples_text, api_key)
            summary_text = result.get("summary", "")
            key_findings = result.get("key_findings", [])
            if isinstance(key_findings, str):
                key_findings = [key_findings]
            single_record = {
                "community_id": comm_id,
                "summary": summary_text,
                "key_findings": key_findings,
                "evidence_count": evidence,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "skipped": False,
            }
            summaries.append(single_record)
            # 2026-05-08 修正：per-item commit（scoped delete + commit, 只動該 community）
            # 原本 batch save at end → 中途卡死全失（少爺揪出的 batch save 設計缺陷）
            if not dry_run:
                if not _save_single_summary(single_record, space_id):
                    # 不丟 exception 中斷迴圈；標記 skipped 讓 main() 的 batch save 重試
                    single_record["skipped"] = True
                    single_record["error"] = "single-item save failed"
                    print(
                        f"  ⚠ per-item save FAILED for {comm_id} — "
                        "fallback to batch retry at end. "
                        "Diagnosis hint: 看 stderr.log POST URL 看 Core API 回 status；"
                        "404 → endpoint 缺；422 → schema mismatch；500 → server error",
                        file=sys.stderr,
                    )
            print(f"ok ({len(summary_text)} chars)")
        except RuntimeError as e:
            print(f"FAILED: {e}", file=sys.stderr)
            summaries.append(
                {
                    "community_id": comm_id,
                    "summary": f"(摘要失敗: {e})",
                    "key_findings": [],
                    "evidence_count": evidence,
                    "generated_at": datetime.now().isoformat(timespec="seconds"),
                    "skipped": True,
                    "error": str(e),
                }
            )

    succeeded = sum(1 for s in summaries if not s.get("skipped"))
    print(
        f"[Phase 3] Done: {succeeded} generated, "
        f"{skipped_unchanged} unchanged (skipped), "
        f"{total - succeeded - skipped_unchanged} other"
    )
    return summaries


# ── Phase 4: POST Summaries to Core API ──────────────────────────────────────
def _save_single_summary(record: dict, space_id: str) -> bool:
    """Per-item save：每筆 LLM 完成立即 POST /summaries/regenerate（scoped delete only this community_id）.

    save_summaries service 內部：DELETE WHERE community_id IN [target] → INSERT → commit。
    所以單筆 send 不會清掉其他 community 的 summaries（即 per-item upsert 行為）。
    """
    url = f"{CORE_API}/api/memvault/kg/summaries/regenerate"
    payload = {
        "space_id": space_id,
        "summaries": [record],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    result = http_post(url, payload, params={"space_id": space_id})
    return "error" not in result


def save_summaries(summaries: list[dict], space_id: str, dry_run: bool) -> bool:
    # Filter out skipped entries — only save actual new/updated summaries
    to_save = [s for s in summaries if not s.get("skipped")]

    if not to_save:
        print("\n[Phase 4] No new summaries to save (all unchanged or skipped)")
        return True

    url = f"{CORE_API}/api/memvault/kg/summaries/upsert"
    payload = {
        "space_id": space_id,
        "summaries": to_save,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }

    if dry_run:
        print(f"\n[Phase 4] DRY RUN — would POST {len(to_save)} summaries to {url}")
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:800])
        return True

    print(f"\n[Phase 4] POSTing {len(to_save)} new/updated summaries to Core API ...")
    result = http_post(url, payload, params={"space_id": space_id})
    if "error" in result:
        # Fallback to regenerate endpoint if upsert not available
        print("[Phase 4] upsert failed, falling back to regenerate ...")
        url_fallback = f"{CORE_API}/api/memvault/kg/summaries/regenerate"
        payload_fb = {
            "space_id": space_id,
            "summaries": to_save,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }
        result = http_post(url_fallback, payload_fb, params={"space_id": space_id})
        if "error" in result:
            print(f"[Phase 4] Core API save failed: {result}", file=sys.stderr)
            return False

    print(f"[Phase 4] {len(to_save)} summaries saved to Core API")
    return True


def print_report(summaries: list[dict]) -> None:
    succeeded = [s for s in summaries if not s.get("skipped")]
    skipped = [s for s in summaries if s.get("skipped")]

    print("\n" + "=" * 60)
    print("  Memvault — Community Summary Pipeline Report")
    print("=" * 60)
    print(f"  Total communities : {len(summaries)}")
    print(f"  Summaries OK      : {len(succeeded)}")
    print(f"  Skipped/failed    : {len(skipped)}")
    print("=" * 60)

    for s in succeeded[:5]:
        print(f"\n  [{s['community_id']}]")
        print(f"    Summary: {s['summary'][:120]}{'...' if len(s['summary']) > 120 else ''}")
        for finding in s.get("key_findings", [])[:2]:
            print(f"    • {finding[:100]}")
    print("\n" + "=" * 60)


# ── Phase 5: Backfill description_zh to L1 Communities ────────────────────────
def backfill_description_zh(summaries: list[dict], dry_run: bool) -> None:
    """Write LLM summary back to each community's description_zh field."""
    succeeded = [s for s in summaries if not s.get("skipped") and s.get("summary")]
    if not succeeded:
        print("\n[Phase 5] No summaries to backfill.")
        return

    print(f"\n[Phase 5] Writing description_zh to {len(succeeded)} communities ...")

    ok_count = 0
    for s in succeeded:
        comm_id = s["community_id"]
        if dry_run:
            continue

        url = f"{CORE_API}/api/memvault/kg/communities/{comm_id}/description"
        payload = {"description_zh": s["summary"]}
        try:
            result = http_post(url, payload)
            if "error" not in result:
                ok_count += 1
            else:
                print(f"  [warn] Failed to update {comm_id}: {result}", file=sys.stderr)
        except Exception as e:
            print(f"  [warn] Failed to update {comm_id}: {e}", file=sys.stderr)

    if dry_run:
        print(f"[Phase 5] DRY RUN — would update {len(succeeded)} communities")
    else:
        print(f"[Phase 5] Updated {ok_count}/{len(succeeded)} communities")


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Memvault community summary pipeline — LLM summarization via DeepSeek V3"
    )
    parser.add_argument("--space-id", default=os.environ.get("MEMVAULT_SPACE_ID", "default"))
    parser.add_argument(
        "--dry-run", action="store_true", help="Print results without calling LLM or saving"
    )
    parser.add_argument(
        "--level",
        type=int,
        default=1,
        choices=[0, 1, 2],
        help="Resolution level to summarize: 0=fine, 1=medium, 2=coarse (default: 1)",
    )
    parser.add_argument(
        "--max-runtime",
        type=int,
        default=MAX_RUNTIME,
        help=f"Max runtime in seconds before saving partial results (default: {MAX_RUNTIME})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate all summaries, even if community content hasn't changed",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=300,
        help="Max communities to process per run (default 300). Prevents OOM "
        "on backlog: 4000+ communities × LLM call easily exceeds 2GB RAM "
        "and the cronicle 1h timeout. Run repeatedly to drain backlog.",
    )
    args = parser.parse_args()

    api_key = DEEPSEEK_API_KEY
    if not api_key and not args.dry_run:
        print("[error] DEEPSEEK_API_KEY environment variable is required", file=sys.stderr)
        sys.exit(1)

    print("Memvault — community_summary_pipeline.py")
    print(f"Core API : {CORE_API}")
    print(f"Space ID : {args.space_id}")
    print(f"Level    : {args.level} (resolution={[1.0, 0.3, 0.05][args.level]})\n")

    # Phase 1: cap fetched community pages so we never load all 4000+ at once.
    # Buffer factor of 3 lets the priority sort still pick from a wider pool.
    fetch_cap = args.limit * 3
    communities = fetch_communities(args.space_id, args.level, max_items=fetch_cap)
    if not communities:
        print("[skip] No communities found at this resolution level.")
        sys.exit(0)

    # Prioritize communities without summaries (then by oldest summary first).
    # This keeps each cron run focused on backlog clearance, not re-processing
    # already-summarized communities. Existing-map fetch is short (HTTP + 200/page).
    if len(communities) > args.limit:
        # Always apply limit (even in dry_run) — fetch_communities returned 4000+
        # records and unbounded iteration easily exceeds 2GB / 1h cronicle budget.
        existing_lookup = _fetch_existing_summaries(args.space_id) if not args.dry_run else {}

        def _priority_key(c):
            comm_id = c.get("community_id", c.get("id", ""))
            existing = existing_lookup.get(comm_id)
            if existing is None:
                return (0, "")  # never summarized → highest priority
            return (1, existing.get("created_at", ""))  # oldest summary next

        communities = sorted(communities, key=_priority_key)[: args.limit]
        print(f"[Phase 1] Limit={args.limit}: prioritized backlog + oldest summaries for this run.")

    # Phase 2 + 3: fetch triples (from community record or API) and generate summaries
    summaries = generate_summaries(
        communities,
        args.space_id,
        api_key,
        args.dry_run,
        max_runtime=args.max_runtime,
        force=args.force,
    )

    # Phase 4
    print_report(summaries)
    ok = save_summaries(summaries, args.space_id, args.dry_run)
    if not ok:
        print("\n[warn] Failed to save summaries to Core API", file=sys.stderr)
        sys.exit(1)

    # Phase 5: Write description_zh back to L1 communities
    backfill_description_zh(summaries, args.dry_run)

    succeeded = sum(1 for s in summaries if not s.get("skipped"))
    print(f"\nDone. {succeeded}/{len(summaries)} summaries saved.")


if __name__ == "__main__":
    main()
