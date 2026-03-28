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
def fetch_communities(space_id: str, resolution_level: int) -> list[dict]:
    url = f"{CORE_API}/api/memvault/kg/communities"
    page_size = 100
    page = 1
    communities: list[dict] = []
    total = None

    print(
        f"[Phase 1] Fetching communities from {url} "
        f"(space={space_id}, level={resolution_level}) ..."
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
def _build_triple_text(triples: list[dict]) -> str:
    lines = []
    for t in triples[:MAX_TRIPLES_IN_PROMPT]:
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


def generate_summaries(
    communities: list[dict],
    space_id: str,
    api_key: str,
    dry_run: bool,
    *,
    max_runtime: int = MAX_RUNTIME,
) -> list[dict]:
    """Generate LLM summaries for each community."""
    summaries: list[dict] = []
    total = len(communities)
    t0 = time.monotonic()

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
            print(f"ok ({len(summary_text)} chars)")
            summaries.append(
                {
                    "community_id": comm_id,
                    "summary": summary_text,
                    "key_findings": key_findings,
                    "evidence_count": evidence,
                    "generated_at": datetime.now().isoformat(timespec="seconds"),
                    "skipped": False,
                }
            )
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
    print(f"[Phase 3] Done: {succeeded}/{total} summaries generated")
    return summaries


# ── Phase 4: POST Summaries to Core API ──────────────────────────────────────
def save_summaries(summaries: list[dict], space_id: str, dry_run: bool) -> bool:
    url = f"{CORE_API}/api/memvault/kg/summaries/regenerate"
    payload = {
        "space_id": space_id,
        "summaries": summaries,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }

    if dry_run:
        print(f"\n[Phase 4] DRY RUN — would POST {len(summaries)} summaries to {url}")
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:800])
        return True

    print(f"\n[Phase 4] POSTing {len(summaries)} summaries to Core API ...")
    result = http_post(url, payload, params={"space_id": space_id})
    if "error" in result:
        print(f"[Phase 4] Core API save failed: {result}", file=sys.stderr)
        return False

    print("[Phase 4] Summaries saved to Core API")
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
    args = parser.parse_args()

    api_key = DEEPSEEK_API_KEY
    if not api_key and not args.dry_run:
        print("[error] DEEPSEEK_API_KEY environment variable is required", file=sys.stderr)
        sys.exit(1)

    print("Memvault — community_summary_pipeline.py")
    print(f"Core API : {CORE_API}")
    print(f"Space ID : {args.space_id}")
    print(f"Level    : {args.level} (resolution={[1.0, 0.3, 0.05][args.level]})\n")

    # Phase 1
    communities = fetch_communities(args.space_id, args.level)
    if not communities:
        print("[skip] No communities found at this resolution level.")
        sys.exit(0)

    # Phase 2 + 3: fetch triples (from community record or API) and generate summaries
    summaries = generate_summaries(
        communities,
        args.space_id,
        api_key,
        args.dry_run,
        max_runtime=args.max_runtime,
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
