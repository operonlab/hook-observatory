#!/usr/bin/env python3
"""Memvault CLI - Command-line interface for the Memvault memory system."""

import argparse
import json
import os
import sys
from datetime import datetime

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL: str = os.environ.get("MEMVAULT_API_URL", "http://localhost:8801")
SPACE_ID: str = os.environ.get("MEMVAULT_SPACE_ID", "default")
API_PREFIX: str = "/api/memvault"

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def api_get(path: str, params: dict | None = None) -> dict:
    """Issue a GET request against the Memvault Core API."""
    url = f"{BASE_URL}{API_PREFIX}{path}"
    p: dict = {"space_id": SPACE_ID}
    if params:
        p.update(params)
    resp = httpx.get(url, params=p, timeout=30)
    resp.raise_for_status()
    return resp.json()


def api_post(path: str, body: dict | None = None) -> dict:
    """Issue a POST request against the Memvault Core API."""
    url = f"{BASE_URL}{API_PREFIX}{path}"
    resp = httpx.post(url, json=body or {}, params={"space_id": SPACE_ID}, timeout=60)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def truncate(text: str, length: int = 300) -> str:
    """Truncate *text* to *length* characters, appending ellipsis if needed."""
    text = text.replace("\n", " ").strip()
    if len(text) <= length:
        return text
    return text[:length] + "..."


def fmt_score(score: float) -> str:
    """Format a similarity score as a fixed-width percentage string."""
    return f"{score:.1%}"


def fmt_tags(tags: list[str]) -> str:
    """Format a list of tags as a comma-separated bracket string."""
    if not tags:
        return ""
    return "[" + ", ".join(tags) + "]"


def fmt_dt(iso: str | None) -> str:
    """Format an ISO datetime string to a short human-friendly form."""
    if not iso:
        return "n/a"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, AttributeError):
        return str(iso)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def cmd_recall(args: argparse.Namespace) -> None:
    """Semantic search over memory blocks."""
    params = {"q": args.query, "top_k": args.top_k, "min_score": args.min_score}
    data = api_get("/search", params)

    if args.json_output:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    results = data if isinstance(data, list) else data.get("results", data.get("blocks", []))
    if not results:
        if not args.quiet:
            print("No results found.")
        return

    for i, item in enumerate(results, 1):
        # Handle both flat ({score, content, ...}) and nested ({score, block: {content, ...}}) formats
        block = item.get("block", item)
        score = item.get("score", block.get("score", 0))
        btype = block.get("block_type", block.get("type", "?"))
        tags = block.get("tags", [])
        content = block.get("content", "")
        if args.quiet:
            print(f"{fmt_score(score)} {truncate(content, 120)}")
        else:
            print(f"  {i}. [{fmt_score(score)}] ({btype}) {fmt_tags(tags)}")
            print(f"     {truncate(content)}")
            print()


def cmd_extract(args: argparse.Namespace) -> None:
    """Create a new memory block."""
    body: dict = {
        "content": args.text,
        "block_type": args.type,
    }
    if args.tags:
        body["tags"] = [t.strip() for t in args.tags.split(",") if t.strip()]
    if args.session:
        body["source_session"] = args.session

    data = api_post("/blocks", body)

    if args.json_output:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    block_id = data.get("id", data.get("block_id", "?"))
    if args.quiet:
        print(block_id)
    else:
        print(f"  Block created: {block_id}")
        print(f"  Type: {args.type}")
        if args.tags:
            print(f"  Tags: {args.tags}")


def cmd_stats(args: argparse.Namespace) -> None:
    """Display aggregate memory statistics."""
    blocks_data = api_get("/blocks", {"page_size": 1})
    tags_data = api_get("/tags")
    profile_data = api_get("/profile")

    if args.json_output:
        combined = {
            "blocks": blocks_data,
            "tags": tags_data,
            "profile": profile_data,
        }
        print(json.dumps(combined, indent=2, ensure_ascii=False))
        return

    # Total blocks
    total = blocks_data.get("total", blocks_data.get("count", "?"))

    # Tags
    tag_list = tags_data if isinstance(tags_data, list) else tags_data.get("tags", [])
    unique_tags = len(tag_list)
    top_tags = tag_list[:20]

    # KAS scores
    kas = profile_data.get("kas", profile_data.get("scores", {}))

    if args.quiet:
        print(f"blocks={total} tags={unique_tags}")
        return

    print("  Memvault Statistics")
    print("  -------------------")
    print(f"  Total blocks : {total}")
    print(f"  Unique tags  : {unique_tags}")
    print()

    if kas:
        print("  KAS Scores:")
        for key, val in kas.items():
            if isinstance(val, (int, float)):
                print(f"    {key:12s}: {val:.2f}")
        print()

    if top_tags:
        print("  Top Tags (up to 20):")
        for t in top_tags:
            if isinstance(t, dict):
                name = t.get("tag", t.get("name", "?"))
                count = t.get("count", "")
                print(f"    - {name}" + (f" ({count})" if count else ""))
            else:
                print(f"    - {t}")


def cmd_profile(args: argparse.Namespace) -> None:
    """Display the KAS profile."""
    params: dict = {}
    if args.rebuild:
        params["rebuild"] = "true"

    data = api_get("/profile", params)

    if args.json_output:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    kas = data.get("kas", data.get("scores", {}))
    updated = data.get("updated_at", data.get("last_updated"))

    if args.quiet:
        for k, v in kas.items():
            if isinstance(v, (int, float)):
                print(f"{k}={v:.2f}")
        return

    print("  KAS Profile")
    print("  -----------")
    for key, val in kas.items():
        if isinstance(val, (int, float)):
            bar = "#" * int(val * 10)
            print(f"  {key:12s}: {val:.2f}  {bar}")
        else:
            print(f"  {key:12s}: {val}")
    print(f"  Updated     : {fmt_dt(updated)}")
    if args.rebuild:
        print("  (rebuilt)")


def cmd_cascade(args: argparse.Namespace) -> None:
    """Knowledge-graph cascade recall."""
    params = {"q": args.query, "top_k": args.top_k}
    data = api_get("/kg/recall", params)

    if args.json_output:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    # Layered display: L2 Wisdom -> L1 Clusters -> L0 Triples -> Blocks
    wisdom = data.get("wisdom", [])
    clusters = data.get("clusters", [])
    triples = data.get("triples", [])
    blocks = data.get("blocks", [])

    if args.quiet:
        for w in wisdom:
            print(f"W: {w.get('wisdom', w.get('insight', w.get('content', '')))[:120]}")
        for b in blocks:
            print(f"B: {b.get('content', '')[:120]}")
        return

    if wisdom:
        print("  L2 - Wisdom")
        print("  " + "-" * 40)
        for w in wisdom:
            text = w.get("wisdom", w.get("insight", w.get("content", "?")))
            conf = w.get("confidence", "?")
            print(f"    [{conf}] {truncate(text, 200)}")
        print()

    if clusters:
        print("  L1 - Clusters")
        print("  " + "-" * 40)
        for c in clusters:
            label = c.get("label", c.get("name", "?"))
            size = c.get("size", c.get("count", "?"))
            print(f"    {label} (size: {size})")
        print()

    if triples:
        print("  L0 - Triples")
        print("  " + "-" * 40)
        for t in triples:
            subj = t.get("subject", "?")
            pred = t.get("predicate", "?")
            obj = t.get("object", "?")
            print(f"    {subj} --[{pred}]--> {obj}")
        print()

    if blocks:
        print("  Blocks")
        print("  " + "-" * 40)
        for b in blocks:
            content = b.get("content", "")
            btype = b.get("block_type", b.get("type", "?"))
            print(f"    ({btype}) {truncate(content, 200)}")
        print()

    if not any([wisdom, clusters, triples, blocks]):
        print("  No cascade results found.")


def cmd_wisdom(args: argparse.Namespace) -> None:
    """List wisdom nodes from the knowledge graph."""
    data = api_get("/kg/wisdom")

    if args.json_output:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    nodes = data if isinstance(data, list) else data.get("wisdom", data.get("nodes", []))

    # Apply filters
    if args.confidence:
        nodes = [n for n in nodes if n.get("confidence", "").upper() == args.confidence.upper()]
    if args.tag:
        nodes = [n for n in nodes if args.tag in n.get("tags", [])]

    if not nodes:
        if not args.quiet:
            print("  No wisdom nodes found.")
        return

    if args.quiet:
        for n in nodes:
            print(n.get("wisdom", n.get("insight", n.get("content", ""))))
        return

    print("  Wisdom Nodes")
    print("  " + "-" * 50)
    for i, n in enumerate(nodes, 1):
        text = n.get("wisdom", n.get("insight", n.get("content", "?")))
        conf = n.get("confidence", "?")
        bridge = n.get("bridge_entity", n.get("bridge", ""))
        evidence = n.get("evidence_count", n.get("evidence", "?"))
        print(f"  {i}. [{conf}] {truncate(text, 200)}")
        if bridge:
            print(f"     Bridge: {bridge}")
        print(f"     Evidence: {evidence}")
        print()


def cmd_attitude(args: argparse.Namespace) -> None:
    """List active attitude facts."""
    data = api_get("/kg/attitudes")

    if args.json_output:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    attitudes = data if isinstance(data, list) else data.get("attitudes", data.get("facts", []))

    # Apply filter
    if args.category:
        attitudes = [a for a in attitudes if a.get("category", "").lower() == args.category.lower()]

    if not attitudes:
        if not args.quiet:
            print("  No attitude facts found.")
        return

    if args.quiet:
        for a in attitudes:
            print(f"{a.get('category', '?')}: {a.get('content', a.get('fact', ''))}")
        return

    print("  Attitude Facts")
    print("  " + "-" * 50)
    for i, a in enumerate(attitudes, 1):
        category = a.get("category", "?")
        content = a.get("content", a.get("fact", "?"))
        conf = a.get("confidence", "?")
        op = a.get("operation", "?")
        print(f"  {i}. [{category}] {truncate(content, 200)}")
        print(f"     Confidence: {conf} | Operation: {op}")
        print()


def cmd_health(args: argparse.Namespace) -> None:
    """Check API connectivity."""
    url = args.api_url or BASE_URL
    data = api_get("/profile")

    if args.json_output:
        print(json.dumps({"status": "healthy", "url": url, "profile": data}, indent=2, ensure_ascii=False))
        return

    if args.quiet:
        print("ok")
    else:
        print(f"  Memvault API healthy ({url})")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    # Shared flags inherited by every subcommand
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", dest="json_output", action="store_true", help="Output raw JSON")
    common.add_argument("--quiet", action="store_true", help="Minimal output")
    common.add_argument("--api-url", dest="api_url", default=None, help="Override MEMVAULT_API_URL")

    parser = argparse.ArgumentParser(
        prog="memvault",
        description="CLI for the Memvault memory system",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # recall
    p_recall = sub.add_parser("recall", parents=[common], help="Semantic search over memory blocks")
    p_recall.add_argument("query", help="Search query")
    p_recall.add_argument("--top-k", type=int, default=5, help="Number of results (default: 5)")
    p_recall.add_argument("--min-score", type=float, default=0.3, help="Minimum similarity score (default: 0.3)")

    # extract
    p_extract = sub.add_parser("extract", parents=[common], help="Create a new memory block")
    p_extract.add_argument("text", help="Block content")
    p_extract.add_argument("--type", choices=["knowledge", "skill", "attitude", "general"], default="general", help="Block type (default: general)")
    p_extract.add_argument("--tags", default=None, help="Comma-separated tags")
    p_extract.add_argument("--session", default=None, help="Source session ID")

    # stats
    sub.add_parser("stats", parents=[common], help="Memory statistics")

    # profile
    p_profile = sub.add_parser("profile", parents=[common], help="KAS profile scores")
    p_profile.add_argument("--rebuild", action="store_true", help="Trigger profile rebuild")

    # cascade
    p_cascade = sub.add_parser("cascade", parents=[common], help="Knowledge-graph cascade recall")
    p_cascade.add_argument("query", help="Search query")
    p_cascade.add_argument("--top-k", type=int, default=5, help="Number of results (default: 5)")

    # wisdom
    p_wisdom = sub.add_parser("wisdom", parents=[common], help="List wisdom nodes")
    p_wisdom.add_argument("--confidence", choices=["HIGH", "MEDIUM", "LOW"], default=None, help="Filter by confidence level")
    p_wisdom.add_argument("--tag", default=None, help="Filter by tag")

    # attitude
    p_attitude = sub.add_parser("attitude", parents=[common], help="List active attitude facts")
    p_attitude.add_argument("--category", default=None, help="Filter by category")

    # health
    sub.add_parser("health", parents=[common], help="API health check")

    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

COMMAND_MAP = {
    "recall": cmd_recall,
    "extract": cmd_extract,
    "stats": cmd_stats,
    "profile": cmd_profile,
    "cascade": cmd_cascade,
    "wisdom": cmd_wisdom,
    "attitude": cmd_attitude,
    "health": cmd_health,
}


def main() -> None:
    global BASE_URL, SPACE_ID

    parser = build_parser()
    args = parser.parse_args()

    # Apply overrides
    if args.api_url:
        BASE_URL = args.api_url
    if os.environ.get("MEMVAULT_API_URL"):
        BASE_URL = os.environ["MEMVAULT_API_URL"]
    if args.api_url:  # CLI flag takes highest priority
        BASE_URL = args.api_url

    handler = COMMAND_MAP.get(args.command)
    if not handler:
        parser.print_help()
        sys.exit(1)

    try:
        handler(args)
    except httpx.ConnectError:
        url = args.api_url or BASE_URL
        print(
            f"  Cannot connect to Memvault API at {url}\n"
            f"  Start server: cd core && uvicorn src.main:app --port 8801",
            file=sys.stderr,
        )
        sys.exit(1)
    except httpx.HTTPStatusError as exc:
        print(
            f"  API error {exc.response.status_code}: {exc.response.text[:500]}",
            file=sys.stderr,
        )
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
