#!/Users/joneshong/.local/bin/python3
"""Memvault CLI - Command-line interface for the Memvault memory system.

Uses the shared workshop SDK client instead of raw HTTP calls.
Full coverage of all Core API endpoints.
"""

import argparse
import json
import os
import sys
from datetime import datetime

from workshop.clients._base import APIConnectionError, APIError
from workshop.clients.memvault import MemvaultClient

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


def _json_out(data, args: argparse.Namespace) -> bool:
    """Print JSON if --json flag is set. Returns True if printed."""
    if args.json_output:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return True
    return False


def _parse_tags(raw: str | None) -> list[str] | None:
    """Parse comma-separated tags string into a list."""
    if not raw:
        return None
    return [t.strip() for t in raw.split(",") if t.strip()]


# ---------------------------------------------------------------------------
# Command handlers — Existing (recall, extract, stats, profile, cascade,
#                               wisdom, attitude, health)
# ---------------------------------------------------------------------------


def cmd_recall(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Semantic search over memory blocks."""
    data = client.recall(
        args.query,
        top_k=args.top_k,
        min_score=args.min_score,
        date_from=getattr(args, "since", None),
        date_to=getattr(args, "before", None),
    )
    if _json_out(data, args):
        return

    results = data if isinstance(data, list) else data.get("results", data.get("blocks", []))
    if not results:
        if not args.quiet:
            print("No results found.")
        return

    for i, item in enumerate(results, 1):
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


def cmd_extract(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Create a new memory block."""
    tags = _parse_tags(args.tags)
    data = client.extract(
        args.text,
        block_type=args.type,
        tags=tags,
        source_session=args.session,
    )
    if _json_out(data, args):
        return

    block_id = data.get("id", data.get("block_id", "?"))
    if args.quiet:
        print(block_id)
    else:
        print(f"  Block created: {block_id}")
        print(f"  Type: {args.type}")
        if args.tags:
            print(f"  Tags: {args.tags}")


def cmd_stats(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Display aggregate memory statistics."""
    data = client.stats()
    if _json_out(data, args):
        return

    blocks_data = data["blocks"]
    tags_data = data["tags"]
    profile_data = data["profile"]

    total = blocks_data.get("total", blocks_data.get("count", "?"))
    tag_list = tags_data if isinstance(tags_data, list) else tags_data.get("tags", [])
    unique_tags = len(tag_list)
    top_tags = tag_list[:20]
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


def cmd_profile(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Display the KAS profile."""
    data = client.profile(rebuild=args.rebuild)
    if _json_out(data, args):
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


def cmd_cascade(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Knowledge-graph cascade recall."""
    data = client.cascade(args.query, top_k=args.top_k)
    if _json_out(data, args):
        return

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


def cmd_wisdom(client: MemvaultClient, args: argparse.Namespace) -> None:
    """List wisdom nodes from the knowledge graph."""
    data = client.wisdom(confidence=args.confidence, tag=args.tag)
    if _json_out(data, args):
        return

    nodes = data if isinstance(data, list) else data.get("wisdom", data.get("nodes", []))

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


def cmd_attitude(client: MemvaultClient, args: argparse.Namespace) -> None:
    """List active attitude facts."""
    data = client.attitudes(category=args.category)
    if _json_out(data, args):
        return

    attitudes = data if isinstance(data, list) else data.get("attitudes", data.get("facts", []))

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


def cmd_health(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Check API connectivity."""
    healthy = client.health()
    if _json_out({"status": "healthy" if healthy else "unhealthy", "url": client.base_url}, args):
        return

    if not healthy:
        print(f"  Memvault API unreachable ({client.base_url})", file=sys.stderr)
        sys.exit(1)

    if args.quiet:
        print("ok")
    else:
        print(f"  Memvault API healthy ({client.base_url})")


# ---------------------------------------------------------------------------
# Command handlers — NEW: Blocks CRUD
# ---------------------------------------------------------------------------


def cmd_blocks(client: MemvaultClient, args: argparse.Namespace) -> None:
    """List memory blocks."""
    data = client.list_blocks(
        page=args.page,
        page_size=args.page_size,
        tag=args.tag,
        block_type=args.type,
    )
    if _json_out(data, args):
        return

    items = data.get("items", [])
    total = data.get("total", "?")

    if not items:
        if not args.quiet:
            print("  No blocks found.")
        return

    if not args.quiet:
        print(f"  Blocks (page {args.page}, {total} total)")
        print("  " + "-" * 60)

    for b in items:
        bid = b.get("id", "?")[:12]
        btype = b.get("block_type", "?")
        tags = fmt_tags(b.get("tags", []))
        content = truncate(b.get("content", ""), 100)
        created = fmt_dt(b.get("created_at"))
        if args.quiet:
            print(f"{bid} ({btype}) {content}")
        else:
            print(f"  {bid}  ({btype}) {tags}  {created}")
            print(f"    {content}")
            print()


def cmd_block_get(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Get a single block by ID."""
    data = client.get_block(args.block_id)
    if _json_out(data, args):
        return

    if args.quiet:
        print(data.get("content", ""))
        return

    print(f"  ID       : {data.get('id', '?')}")
    print(f"  Type     : {data.get('block_type', '?')}")
    print(f"  Tags     : {fmt_tags(data.get('tags', []))}")
    print(f"  Created  : {fmt_dt(data.get('created_at'))}")
    print(f"  Updated  : {fmt_dt(data.get('updated_at'))}")
    print(f"  Session  : {data.get('source_session', 'n/a')}")
    print()
    print(data.get("content", ""))


def cmd_block_update(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Update a memory block."""
    fields: dict = {}
    if args.content:
        fields["content"] = args.content
    if args.type:
        fields["block_type"] = args.type
    if args.tags is not None:
        fields["tags"] = _parse_tags(args.tags) or []

    if not fields:
        print("  No fields to update. Use --content, --type, or --tags.", file=sys.stderr)
        sys.exit(1)

    data = client.update_block(args.block_id, **fields)
    if _json_out(data, args):
        return

    if args.quiet:
        print(data.get("id", "?"))
    else:
        print(f"  Block updated: {data.get('id', '?')}")


def cmd_block_delete(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Delete a memory block."""
    client.delete_block(args.block_id)
    if _json_out({"deleted": args.block_id}, args):
        return
    if not args.quiet:
        print(f"  Block deleted: {args.block_id}")


# ---------------------------------------------------------------------------
# Command handlers — NEW: Tags
# ---------------------------------------------------------------------------


def cmd_tags(client: MemvaultClient, args: argparse.Namespace) -> None:
    """List all tags."""
    data = client.list_tags()
    if _json_out(data, args):
        return

    tags = data if isinstance(data, list) else data.get("tags", [])
    if not tags:
        if not args.quiet:
            print("  No tags found.")
        return

    for t in tags:
        if isinstance(t, dict):
            name = t.get("tag", t.get("name", "?"))
            count = t.get("count", "")
            if args.quiet:
                print(f"{name} {count}")
            else:
                print(f"  {name:30s} ({count})")
        else:
            print(f"  {t}")


def cmd_tags_sync(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Sync tag counts."""
    data = client.sync_tags()
    if _json_out(data, args):
        return

    synced = data.get("synced", "?")
    if args.quiet:
        print(synced)
    else:
        print(f"  Tags synced: {synced}")


# ---------------------------------------------------------------------------
# Command handlers — NEW: Domains
# ---------------------------------------------------------------------------


def cmd_domains(client: MemvaultClient, args: argparse.Namespace) -> None:
    """List knowledge domains."""
    data = client.list_domains(page=args.page, page_size=args.page_size)
    if _json_out(data, args):
        return

    items = data.get("items", [])
    if not items:
        if not args.quiet:
            print("  No domains found.")
        return

    for d in items:
        did = d.get("id", "?")[:12]
        name = d.get("name", "?")
        desc = d.get("description", "")
        if args.quiet:
            print(f"{did} {name}")
        else:
            print(f"  {did}  {name}")
            if desc:
                print(f"    {truncate(desc, 100)}")
            print()


def cmd_domain_create(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Create a knowledge domain."""
    data = client.create_domain(args.name, description=args.description)
    if _json_out(data, args):
        return

    if args.quiet:
        print(data.get("id", "?"))
    else:
        print(f"  Domain created: {data.get('id', '?')} ({args.name})")


def cmd_domain_update(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Update a knowledge domain."""
    fields: dict = {}
    if args.name:
        fields["name"] = args.name
    if args.description:
        fields["description"] = args.description
    data = client.update_domain(args.domain_id, **fields)
    if _json_out(data, args):
        return

    if args.quiet:
        print(data.get("id", "?"))
    else:
        print(f"  Domain updated: {data.get('id', '?')}")


# ---------------------------------------------------------------------------
# Command handlers — NEW: Triples
# ---------------------------------------------------------------------------


def cmd_triples(client: MemvaultClient, args: argparse.Namespace) -> None:
    """List KG triples."""
    data = client.list_triples(
        predicate=args.predicate,
        subject=args.subject,
        page=args.page,
        page_size=args.page_size,
    )
    if _json_out(data, args):
        return

    items = data.get("items", [])
    total = data.get("total", "?")

    if not items:
        if not args.quiet:
            print("  No triples found.")
        return

    if not args.quiet:
        print(f"  Triples (page {args.page}, {total} total)")
        print("  " + "-" * 60)

    for t in items:
        subj = t.get("subject", "?")
        pred = t.get("predicate", "?")
        obj = t.get("object", "?")
        conf = t.get("confidence")
        tid = t.get("id", "?")[:12]
        if args.quiet:
            print(f"{subj} --[{pred}]--> {obj}")
        else:
            conf_str = f" ({conf:.2f})" if conf is not None else ""
            print(f"  {tid}  {subj} --[{pred}]--> {obj}{conf_str}")


def cmd_triple_search(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Semantic search over triples."""
    data = client.search_triples(args.query, top_k=args.top_k)
    if _json_out(data, args):
        return

    results = data if isinstance(data, list) else data.get("results", [])
    if not results:
        if not args.quiet:
            print("  No matching triples found.")
        return

    for t in results:
        subj = t.get("subject", "?")
        pred = t.get("predicate", "?")
        obj = t.get("object", "?")
        print(f"  {subj} --[{pred}]--> {obj}")


# ---------------------------------------------------------------------------
# Command handlers — NEW: Clusters
# ---------------------------------------------------------------------------


def cmd_clusters(client: MemvaultClient, args: argparse.Namespace) -> None:
    """List KG clusters."""
    data = client.list_clusters()
    if _json_out(data, args):
        return

    clusters = data if isinstance(data, list) else data.get("clusters", [])
    if not clusters:
        if not args.quiet:
            print("  No clusters found.")
        return

    if not args.quiet:
        print(f"  Clusters ({len(clusters)} total)")
        print("  " + "-" * 50)

    for c in clusters:
        cid = c.get("id", "?")[:12]
        name = c.get("name", c.get("label", "?"))
        size = c.get("size", "?")
        verdict = c.get("verdict", "")
        if args.quiet:
            print(f"{name} (size: {size})")
        else:
            verdict_str = f" [{verdict}]" if verdict else ""
            print(f"  {cid}  {name} (size: {size}){verdict_str}")


def cmd_cluster_get(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Get cluster detail."""
    data = client.get_cluster(args.cluster_id)
    if _json_out(data, args):
        return

    if args.quiet:
        print(data.get("name", data.get("label", "?")))
        return

    print(f"  ID       : {data.get('id', '?')}")
    print(f"  Name     : {data.get('name', data.get('label', '?'))}")
    print(f"  Size     : {data.get('size', '?')}")
    print(f"  Verdict  : {data.get('verdict', 'n/a')}")
    summary = data.get("summary")
    if summary:
        print(f"  Summary  : {truncate(summary, 200)}")
    members = data.get("members", [])
    if members:
        print(f"  Members ({len(members)}):")
        for m in members[:20]:
            tid = m.get("triple_id", m.get("id", "?"))[:12]
            print(f"    - {tid}")
        if len(members) > 20:
            print(f"    ... and {len(members) - 20} more")


# ---------------------------------------------------------------------------
# Command handlers — NEW: Attitude extended
# ---------------------------------------------------------------------------


def cmd_attitude_history(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Get attitude fact evolution history."""
    data = client.attitude_history(args.fact_id)
    if _json_out(data, args):
        return

    facts = data if isinstance(data, list) else data.get("history", [])
    if not facts:
        if not args.quiet:
            print("  No history found.")
        return

    if not args.quiet:
        print(f"  Attitude History for {args.fact_id[:12]}...")
        print("  " + "-" * 50)

    for a in facts:
        fid = a.get("id", "?")[:12]
        fact = a.get("fact", a.get("content", "?"))
        op = a.get("operation", "?")
        conf = a.get("confidence", "?")
        created = fmt_dt(a.get("created_at"))
        if args.quiet:
            print(f"{op} {fact}")
        else:
            print(f"  {fid}  [{op}] confidence={conf}  {created}")
            print(f"    {truncate(fact, 200)}")
            print()


# ---------------------------------------------------------------------------
# Command handlers — NEW: Skill history
# ---------------------------------------------------------------------------


def cmd_skill_history(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Get invocation history for a skill."""
    data = client.skill_history(args.skill_name, limit=args.limit)
    if _json_out(data, args):
        return

    invocations = data if isinstance(data, list) else data.get("invocations", [])
    if not invocations:
        if not args.quiet:
            print(f"  No history for '{args.skill_name}'.")
        return

    if not args.quiet:
        print(f"  Skill History: {args.skill_name} ({len(invocations)} invocations)")
        print("  " + "-" * 50)

    for inv in invocations:
        iid = inv.get("id", "?")[:12]
        outcome = inv.get("outcome", "?")
        duration = inv.get("duration_ms")
        created = fmt_dt(inv.get("created_at"))
        dur_str = f" {duration}ms" if duration else ""
        if args.quiet:
            print(f"{outcome}{dur_str} {created}")
        else:
            print(f"  {iid}  {outcome}{dur_str}  {created}")


# ---------------------------------------------------------------------------
# Command handlers — NEW: Frozen tier
# ---------------------------------------------------------------------------


def cmd_frozen(client: MemvaultClient, args: argparse.Namespace) -> None:
    """List frozen blocks."""
    data = client.list_frozen(
        page=args.page,
        page_size=args.page_size,
        block_type=args.type,
        tag=args.tag,
    )
    if _json_out(data, args):
        return

    items = data.get("items", [])
    total = data.get("total", "?")

    if not items:
        if not args.quiet:
            print("  No frozen blocks found.")
        return

    if not args.quiet:
        print(f"  Frozen Blocks (page {args.page}, {total} total)")
        print("  " + "-" * 60)

    for b in items:
        bid = b.get("id", "?")[:12]
        btype = b.get("block_type", "?")
        tags = fmt_tags(b.get("tags", []))
        summary = truncate(b.get("summary", ""), 80)
        size = b.get("content_size", "?")
        frozen_at = fmt_dt(b.get("frozen_at"))
        if args.quiet:
            print(f"{bid} ({btype}) {summary}")
        else:
            print(f"  {bid}  ({btype}) {tags}  frozen={frozen_at}  size={size}")
            if summary:
                print(f"    {summary}")
            print()


def cmd_thaw(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Thaw a frozen block."""
    data = client.thaw_frozen(args.block_id)
    if _json_out(data, args):
        return

    content = data.get("content", "")
    if args.quiet:
        if isinstance(content, dict):
            print(json.dumps(content, ensure_ascii=False))
        else:
            print(str(content))
    else:
        print(f"  Thawed block: {args.block_id}")
        print(f"  Frozen at: {fmt_dt(data.get('frozen_at'))}")
        print()
        if isinstance(content, dict):
            print(json.dumps(content, indent=2, ensure_ascii=False))
        else:
            print(content)


# ---------------------------------------------------------------------------
# Command handlers — NEW: Admin / Maintenance
# ---------------------------------------------------------------------------


def cmd_status(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Module status."""
    data = client.status()
    if _json_out(data, args):
        return

    if args.quiet:
        print(data.get("status", "?"))
    else:
        print(f"  Module : {data.get('module', '?')}")
        print(f"  Status : {data.get('status', '?')}")
        print(f"  Phase  : {data.get('phase', '?')}")


def cmd_recalculate(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Recalculate KAS profile from KG data."""
    data = client.recalculate_profile()
    if _json_out(data, args):
        return

    if args.quiet:
        k = data.get("knowledge_score", 0)
        a = data.get("attitude_score", 0)
        s = data.get("skill_score", 0)
        print(f"K={k:.1f} A={a:.1f} S={s:.1f}")
    else:
        print("  KAS Profile (recalculated)")
        print("  -------------------------")
        print(f"  Knowledge : {data.get('knowledge_score', 0):.1f}")
        print(f"  Attitude  : {data.get('attitude_score', 0):.1f}")
        print(f"  Skill     : {data.get('skill_score', 0):.1f}")


def cmd_decay(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Apply confidence decay to attitude facts."""
    data = client.apply_decay()
    if _json_out(data, args):
        return

    checked = data.get("checked", "?")
    updated = data.get("updated", "?")
    if args.quiet:
        print(f"checked={checked} updated={updated}")
    else:
        print(f"  Decay applied: checked={checked}, updated={updated}")


def cmd_backfill(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Backfill missing embeddings."""
    data = client.backfill_embeddings(batch_size=args.batch_size)
    if _json_out(data, args):
        return

    triples = data.get("triples", {})
    attitudes = data.get("attitudes", {})
    if args.quiet:
        print(f"triples={triples.get('updated', 0)} attitudes={attitudes.get('updated', 0)}")
    else:
        print("  Embedding Backfill")
        print("  ------------------")
        t_u = triples.get("updated", 0)
        t_m = triples.get("total_missing", 0)
        a_u = attitudes.get("updated", 0)
        a_m = attitudes.get("total_missing", 0)
        print(f"  Triples   : {t_u} / {t_m} backfilled")
        print(f"  Attitudes : {a_u} / {a_m} backfilled")


def cmd_sync_stats(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Show sync/extraction statistics."""
    data = client.sync_stats()
    if _json_out(data, args):
        return

    if args.quiet:
        print(f"synced={data.get('synced', '?')}")
    else:
        print(f"  Total sessions : {data.get('total', '?')}")
        print(f"  Synced         : {data.get('synced', '?')}")
        print(f"  Failed         : {data.get('failed', '?')}")
        print(f"  Skipped        : {data.get('skipped', '?')}")


def cmd_sync_scan(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Trigger a sync scan for new memories."""
    data = client.sync_scan()
    if _json_out(data, args):
        return

    if args.quiet:
        print(data.get("status", "ok"))
    else:
        print(f"  Sync scan: {data.get('status', 'ok')}")


# ---------------------------------------------------------------------------
# Command handlers — NEW: Missing commands from review
# ---------------------------------------------------------------------------


def cmd_skill_proficiency(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Show skill proficiency ranking."""
    data = client.skill_proficiency()
    if _json_out(data, args):
        return

    skills = data if isinstance(data, list) else data.get("skills", [])
    if not skills:
        if not args.quiet:
            print("  No skill proficiency data.")
        return

    if not args.quiet:
        print("  Skill Proficiency Ranking")
        print("  " + "-" * 50)

    for i, s in enumerate(skills, 1):
        name = s.get("skill_name", s.get("name", "?"))
        count = s.get("invocation_count", s.get("count", 0))
        success = s.get("success_rate", s.get("rate", 0))
        if args.quiet:
            print(f"{name} count={count} success={success:.0%}")
        else:
            print(f"  {i}. {name:30s} invocations={count}  success={success:.0%}")


def cmd_triple_create(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Create a KG triple."""
    data = client.create_triple(
        args.subject,
        args.predicate,
        args.object,
        confidence=args.confidence,
        source_session=args.session,
    )
    if _json_out(data, args):
        return

    if args.quiet:
        print(data.get("id", "?"))
    else:
        print(f"  Triple created: {data.get('id', '?')}")
        print(f"  {args.subject} --[{args.predicate}]--> {args.object}")


def cmd_triple_delete(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Delete a KG triple."""
    client.delete_triple(args.triple_id)
    if _json_out({"deleted": args.triple_id}, args):
        return
    if not args.quiet:
        print(f"  Triple deleted: {args.triple_id}")


def cmd_attitude_create(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Create an attitude fact."""
    data = client.create_attitude(
        args.fact,
        args.category,
        confidence=args.confidence,
    )
    if _json_out(data, args):
        return

    if args.quiet:
        print(data.get("id", "?"))
    else:
        print(f"  Attitude created: {data.get('id', '?')}")
        print(f"  [{args.category}] {args.fact}")


def cmd_attitude_evolve(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Evolve an attitude fact (ADD/UPDATE/NOOP)."""
    data = client.attitude_evolve(
        args.fact,
        args.category,
        source_session=args.session,
    )
    if _json_out(data, args):
        return

    op = data.get("operation", "?")
    fid = data.get("id", data.get("fact_id", "?"))
    if args.quiet:
        print(f"{op} {fid}")
    else:
        print(f"  Attitude evolved: {op}")
        print(f"  Fact ID: {fid}")


def cmd_attitude_delete(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Delete an attitude fact."""
    client.delete_attitude(args.fact_id)
    if _json_out({"deleted": args.fact_id}, args):
        return
    if not args.quiet:
        print(f"  Attitude deleted: {args.fact_id}")


def cmd_profile_upsert(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Upsert KAS profile scores."""
    data = client.upsert_profile(
        knowledge_score=args.knowledge,
        attitude_score=args.attitude,
        skill_score=args.skill,
    )
    if _json_out(data, args):
        return

    if args.quiet:
        k = data.get("knowledge_score", 0)
        a = data.get("attitude_score", 0)
        s = data.get("skill_score", 0)
        print(f"K={k} A={a} S={s}")
    else:
        print("  Profile updated:")
        print(f"  Knowledge : {data.get('knowledge_score', 0)}")
        print(f"  Attitude  : {data.get('attitude_score', 0)}")
        print(f"  Skill     : {data.get('skill_score', 0)}")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", dest="json_output", action="store_true", help="Output raw JSON")
    common.add_argument("--quiet", action="store_true", help="Minimal output")
    common.add_argument("--api-url", dest="api_url", default=None, help="Override MEMVAULT_API_URL")

    # Pagination mixin
    paginated = argparse.ArgumentParser(add_help=False)
    paginated.add_argument("--page", type=int, default=1, help="Page number (default: 1)")
    paginated.add_argument("--page-size", type=int, default=20, help="Items per page (default: 20)")

    parser = argparse.ArgumentParser(
        prog="memvault",
        description="CLI for the Memvault memory system",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ---- Existing commands ----

    # recall
    p = sub.add_parser("recall", parents=[common], help="Semantic search over memory blocks")
    p.add_argument("query", help="Search query")
    p.add_argument("--top-k", type=int, default=5, help="Number of results (default: 5)")
    p.add_argument(
        "--min-score",
        type=float,
        default=0.3,
        help="Minimum similarity score (default: 0.3)",
    )
    p.add_argument("--since", help="Filter: created_at >= date (ISO format, e.g. 2026-03-01)")
    p.add_argument("--before", help="Filter: created_at <= date (ISO format, e.g. 2026-03-11)")

    # extract
    p = sub.add_parser("extract", parents=[common], help="Create a new memory block")
    p.add_argument("text", help="Block content")
    p.add_argument(
        "--type",
        choices=["knowledge", "skill", "attitude", "general"],
        default="general",
        help="Block type (default: general)",
    )
    p.add_argument("--tags", default=None, help="Comma-separated tags")
    p.add_argument("--session", default=None, help="Source session ID")

    # stats
    sub.add_parser("stats", parents=[common], help="Memory statistics")

    # profile
    p = sub.add_parser("profile", parents=[common], help="KAS profile scores")
    p.add_argument("--rebuild", action="store_true", help="Trigger profile rebuild")

    # cascade
    p = sub.add_parser("cascade", parents=[common], help="Knowledge-graph cascade recall")
    p.add_argument("query", help="Search query")
    p.add_argument("--top-k", type=int, default=5, help="Number of results (default: 5)")

    # wisdom
    p = sub.add_parser("wisdom", parents=[common], help="List wisdom nodes")
    p.add_argument(
        "--confidence",
        choices=["HIGH", "MEDIUM", "LOW"],
        default=None,
        help="Filter by confidence level",
    )
    p.add_argument("--tag", default=None, help="Filter by tag")

    # attitude
    p = sub.add_parser("attitude", parents=[common], help="List active attitude facts")
    p.add_argument("--category", default=None, help="Filter by category")

    # health
    sub.add_parser("health", parents=[common], help="API health check")

    # ---- NEW: Blocks CRUD ----

    # blocks (list)
    p = sub.add_parser("blocks", parents=[common, paginated], help="List memory blocks")
    p.add_argument("--tag", default=None, help="Filter by tag")
    p.add_argument("--type", default=None, help="Filter by block type")

    # block (get)
    p = sub.add_parser("block", parents=[common], help="Get a single block by ID")
    p.add_argument("block_id", help="Block ID")

    # block-update
    p = sub.add_parser("block-update", parents=[common], help="Update a memory block")
    p.add_argument("block_id", help="Block ID")
    p.add_argument("--content", default=None, help="New content")
    p.add_argument("--type", default=None, help="New block type")
    p.add_argument("--tags", default=None, help="New comma-separated tags (empty string to clear)")

    # block-delete
    p = sub.add_parser("block-delete", parents=[common], help="Delete a memory block")
    p.add_argument("block_id", help="Block ID")

    # ---- NEW: Tags ----

    sub.add_parser("tags", parents=[common], help="List all tags")
    sub.add_parser("tags-sync", parents=[common], help="Sync tag counts from blocks")

    # ---- NEW: Domains ----

    sub.add_parser("domains", parents=[common, paginated], help="List knowledge domains")

    p = sub.add_parser("domain-create", parents=[common], help="Create a knowledge domain")
    p.add_argument("name", help="Domain name")
    p.add_argument("--description", default=None, help="Domain description")

    p = sub.add_parser("domain-update", parents=[common], help="Update a knowledge domain")
    p.add_argument("domain_id", help="Domain ID")
    p.add_argument("--name", default=None, help="New name")
    p.add_argument("--description", default=None, help="New description")

    # ---- NEW: KG Triples ----

    p = sub.add_parser("triples", parents=[common, paginated], help="List KG triples")
    p.add_argument("--predicate", default=None, help="Filter by predicate")
    p.add_argument("--subject", default=None, help="Filter by subject")

    p = sub.add_parser("triple-search", parents=[common], help="Semantic search over triples")
    p.add_argument("query", help="Search query")
    p.add_argument("--top-k", type=int, default=10, help="Number of results (default: 10)")

    # ---- NEW: KG Clusters ----

    sub.add_parser("clusters", parents=[common], help="List KG clusters")

    p = sub.add_parser("cluster", parents=[common], help="Get cluster detail")
    p.add_argument("cluster_id", help="Cluster ID")

    # ---- NEW: Attitude extended ----

    p = sub.add_parser("attitude-history", parents=[common], help="Attitude fact evolution history")
    p.add_argument("fact_id", help="Attitude fact ID")

    # ---- NEW: Skill history ----

    p = sub.add_parser("skill-history", parents=[common], help="Skill invocation history")
    p.add_argument("skill_name", help="Skill name")
    p.add_argument("--limit", type=int, default=20, help="Max results (default: 20)")

    # ---- NEW: Frozen tier ----

    p = sub.add_parser("frozen", parents=[common, paginated], help="List frozen blocks")
    p.add_argument("--tag", default=None, help="Filter by tag")
    p.add_argument("--type", default=None, help="Filter by block type")

    p = sub.add_parser("thaw", parents=[common], help="Thaw a frozen block")
    p.add_argument("block_id", help="Frozen block ID")

    # ---- NEW: Admin / Maintenance ----

    sub.add_parser("status", parents=[common], help="Module status")
    sub.add_parser("recalculate", parents=[common], help="Recalculate KAS profile from KG data")
    sub.add_parser("decay", parents=[common], help="Apply confidence decay to attitude facts")
    sub.add_parser("sync-stats", parents=[common], help="Show sync/extraction statistics")

    p = sub.add_parser("backfill", parents=[common], help="Backfill missing embeddings")
    p.add_argument("--batch-size", type=int, default=50, help="Batch size (default: 50)")

    sub.add_parser("sync-scan", parents=[common], help="Trigger sync scan for new memories")

    # ---- NEW: Missing commands from review ----

    # skill-proficiency
    sub.add_parser("skill-proficiency", parents=[common], help="Skill proficiency ranking")

    # triple-create
    p = sub.add_parser("triple-create", parents=[common], help="Create a KG triple")
    p.add_argument("subject", help="Subject entity")
    p.add_argument("predicate", help="Predicate/relation")
    p.add_argument("object", help="Object entity")
    p.add_argument("--confidence", type=float, default=None, help="Confidence (0.0-1.0)")
    p.add_argument("--session", default=None, help="Source session ID")

    # triple-delete
    p = sub.add_parser("triple-delete", parents=[common], help="Delete a KG triple")
    p.add_argument("triple_id", help="Triple ID")

    # attitude-create
    p = sub.add_parser("attitude-create", parents=[common], help="Create an attitude fact")
    p.add_argument("fact", help="Attitude fact text")
    p.add_argument("category", help="Category (e.g. preference, belief, value)")
    p.add_argument("--confidence", type=float, default=None, help="Confidence (0.0-1.0)")

    # attitude-evolve
    p = sub.add_parser(
        "attitude-evolve",
        parents=[common],
        help="Evolve an attitude (ADD/UPDATE/NOOP)",
    )
    p.add_argument("fact", help="Attitude fact text")
    p.add_argument("category", help="Category")
    p.add_argument("--session", default=None, help="Source session ID")

    # attitude-delete
    p = sub.add_parser("attitude-delete", parents=[common], help="Delete an attitude fact")
    p.add_argument("fact_id", help="Attitude fact ID")

    # profile-upsert
    p = sub.add_parser("profile-upsert", parents=[common], help="Upsert KAS profile scores")
    p.add_argument("--knowledge", type=float, default=None, help="Knowledge score")
    p.add_argument("--attitude", type=float, default=None, help="Attitude score")
    p.add_argument("--skill", type=float, default=None, help="Skill score")

    # ---- Edge Invalidation + Entity Resolution + Graph Traversal ----

    p = sub.add_parser("triple-invalidate", parents=[common], help="Invalidate a triple")
    p.add_argument("triple_id", help="Triple ID")
    p.add_argument("--reason", default="manual", help="Invalidation reason")
    p.add_argument("--replacement", default=None, help="Replacement triple ID")

    p = sub.add_parser("entities", parents=[common, paginated], help="List canonical entities")
    p.add_argument("--type", default=None, help="Entity type filter")

    sub.add_parser("entity-stats", parents=[common], help="Entity resolution statistics")

    p = sub.add_parser("entity-merge", parents=[common], help="Merge two entities")
    p.add_argument("primary_id", help="Primary entity ID (kept)")
    p.add_argument("secondary_id", help="Secondary entity ID (merged into primary)")

    p = sub.add_parser("entity-merge-candidates", parents=[common], help="Find merge candidates")
    p.add_argument("--threshold", type=float, default=0.92, help="Similarity threshold")
    p.add_argument("--limit", type=int, default=50, help="Max candidates")

    sub.add_parser("entity-backfill", parents=[common], help="Backfill entity resolution")

    p = sub.add_parser(
        "entity-auto-merge",
        parents=[common],
        help="Auto-merge entities above similarity threshold",
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=0.95,
        help="Similarity threshold (default: 0.95)",
    )
    p.add_argument(
        "--max-merges",
        type=int,
        default=20,
        help="Max merges per run (default: 20)",
    )

    p = sub.add_parser("traverse", parents=[common], help="Multi-hop graph traversal")
    p.add_argument("entity", help="Seed entity name")
    p.add_argument("--depth", type=int, default=2, help="Max traversal depth (1-4)")
    p.add_argument("--direction", default="both", choices=["outgoing", "incoming", "both"])
    p.add_argument("--predicates", default=None, help="Comma-separated predicate filter")
    p.add_argument("--max-results", type=int, default=200, help="Max results (1-500)")

    # Session context (flywheel bridge)
    p = sub.add_parser(
        "session-context",
        parents=[common],
        help="Get all blocks + triples + entities for a session",
    )
    p.add_argument("source_session", help="Source session identifier")

    # Intelligence ingest (flywheel bridge)
    p = sub.add_parser(
        "intelligence-ingest",
        parents=[common],
        help="Ingest intelligence digest into memvault",
    )
    p.add_argument("content", help="Digest content text")
    p.add_argument(
        "--digest-type",
        default="weekly",
        choices=["daily", "weekly"],
    )
    p.add_argument("--period", default="", help="Period label (e.g., 2026-W11)")

    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Command handlers — Edge Invalidation, Entity Resolution, Graph Traversal
# ---------------------------------------------------------------------------


def cmd_triple_invalidate(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Invalidate a triple (soft temporal invalidation)."""
    data = client.invalidate_triple(
        args.triple_id,
        reason=args.reason,
        replacement_id=getattr(args, "replacement", None),
    )
    if _json_out(data, args):
        return
    print(f"  Triple {args.triple_id} invalidated (reason: {args.reason})")


def cmd_entities(client: MemvaultClient, args: argparse.Namespace) -> None:
    """List canonical entities."""
    data = client.list_entities(
        entity_type=getattr(args, "type", None),
        page=args.page,
        page_size=args.page_size,
    )
    if _json_out(data, args):
        return
    items = data.get("items", [])
    total = data.get("total", len(items))
    if not items:
        print("  No entities found.")
        return
    print(f"  Canonical Entities ({total} total)")
    print(f"  {'─' * 60}")
    for e in items:
        aliases = ", ".join(e.get("aliases", [])[:3])
        merge = e.get("merge_count", 1)
        etype = e.get("entity_type", "concept")
        print(f"  {e['canonical_name']:<40s} [{etype}] merges={merge}")
        if aliases:
            print(f"    aliases: {aliases}")


def cmd_entity_stats(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Entity resolution statistics."""
    data = client.entity_stats()
    if _json_out(data, args):
        return
    print("  Entity Resolution Stats")
    print(f"  {'─' * 30}")
    print(f"  Total entities   : {data.get('total_entities', 0)}")
    print(f"  Total aliases    : {data.get('total_aliases', 0)}")
    print(f"  Avg merge count  : {data.get('avg_merge_count', 1.0):.2f}")
    print(f"  Unresolved triples: {data.get('unresolved_triples', 0)}")


def cmd_entity_merge(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Merge two entities."""
    data = client.merge_entities(args.primary_id, args.secondary_id)
    if _json_out(data, args):
        return
    print(f"  Merged → {data.get('canonical_name', '?')}")
    print(f"  Aliases: {', '.join(data.get('aliases', []))}")
    print(f"  Triples updated: {data.get('triples_updated', 0)}")


def cmd_entity_merge_candidates(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Find entity merge candidates by embedding similarity."""
    data = client.entity_merge_candidates(
        threshold=getattr(args, "threshold", 0.92),
        limit=getattr(args, "limit", 50),
    )
    if _json_out(data, args):
        return
    if not data:
        print("  No merge candidates found.")
        return
    print(f"  Merge Candidates ({len(data)} pairs)")
    print(f"  {'─' * 70}")
    for c in data:
        p = c.get("primary", {})
        s = c.get("secondary", {})
        sim = c.get("similarity", 0)
        pn = p.get("canonical_name", "?")
        sn = s.get("canonical_name", "?")
        print(f"  {pn:<30s} ↔ {sn:<30s} sim={sim:.4f}")


def cmd_entity_backfill(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Backfill entity resolution for unresolved triples."""
    data = client.backfill_entity_resolution()
    if _json_out(data, args):
        return
    resolved = data.get("resolved", 0)
    total = data.get("total_unresolved", 0)
    print(f"  Entity backfill: {resolved} resolved out of {total}")


def cmd_entity_auto_merge(
    client: MemvaultClient,
    args: argparse.Namespace,
) -> None:
    """Auto-merge entities above similarity threshold."""
    data = client._post(
        "/kg/entities/auto-merge",
        params={
            "space_id": args.space_id,
            "threshold": args.threshold,
            "max_merges": args.max_merges,
        },
    )
    if _json_out(data, args):
        return
    merged = data.get("merged", 0)
    print(f"  Auto-merged: {merged} entity pairs")
    for d in data.get("details", []):
        cn = d.get("canonical_name", "?")
        tu = d.get("triples_updated", 0)
        print(f"    {cn} ({tu} triples updated)")


def cmd_traverse(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Multi-hop graph traversal from a seed entity."""
    data = client.graph_traverse(
        entity=args.entity,
        max_depth=args.depth,
        direction=args.direction,
        predicates=getattr(args, "predicates", None),
        max_results=getattr(args, "max_results", 200),
    )
    if _json_out(data, args):
        return
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    truncated = data.get("truncated", False)
    print(f"  Graph Traversal: {data.get('seed_entity', '?')}")
    print(f"  Direction: {data.get('direction', '?')} | Max depth: {data.get('max_depth', '?')}")
    print(f"  Nodes: {len(nodes)} | Edges: {len(edges)}{' (TRUNCATED)' if truncated else ''}")
    print()
    for edge in edges[:50]:
        d = edge.get("depth", "?")
        print(f"  [d={d}] {edge['source']} --[{edge['predicate']}]--> {edge['target']}")
    if len(edges) > 50:
        print(f"  ... and {len(edges) - 50} more edges")


def cmd_session_context(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Get all blocks + triples + entities for a source_session."""
    data = client._get(
        "/kg/session-context",
        params={
            "source_session": args.source_session,
            "space_id": args.space_id,
        },
    )
    if _json_out(data, args):
        return
    s = data.get("summary", {})
    print(f"  Session: {data.get('source_session', '?')}")
    print(f"  Blocks: {s.get('total_blocks', 0)}")
    print(f"  Triples: {s.get('total_triples', 0)}")
    print(f"  Entities: {s.get('total_entities', 0)}")
    print()
    for b in data.get("blocks", []):
        print(f"  [block] [{b['block_type']}] {b['content'][:80]}...")
    for t in data.get("triples", []):
        print(f"  [triple] {t['subject']} --{t['predicate']}--> {t['object']}")
    for e in data.get("entities", []):
        print(f"  [entity] {e['canonical_name']} ({e['entity_type']})")


def cmd_intelligence_ingest(client: MemvaultClient, args: argparse.Namespace) -> None:
    """Ingest intelligence digest into memvault."""
    data = client._post(
        "/kg/intelligence/ingest",
        params={
            "space_id": args.space_id,
            "digest_type": args.digest_type,
            "period": args.period,
            "content": args.content,
        },
    )
    if _json_out(data, args):
        return
    print(f"  Status: {data.get('status', '?')}")
    print(f"  Type: {data.get('digest_type', '?')}")
    print(f"  Period: {data.get('period', '?')}")


COMMAND_MAP = {
    # Existing
    "recall": cmd_recall,
    "extract": cmd_extract,
    "stats": cmd_stats,
    "profile": cmd_profile,
    "cascade": cmd_cascade,
    "wisdom": cmd_wisdom,
    "attitude": cmd_attitude,
    "health": cmd_health,
    # Blocks CRUD
    "blocks": cmd_blocks,
    "block": cmd_block_get,
    "block-update": cmd_block_update,
    "block-delete": cmd_block_delete,
    # Tags
    "tags": cmd_tags,
    "tags-sync": cmd_tags_sync,
    # Domains
    "domains": cmd_domains,
    "domain-create": cmd_domain_create,
    "domain-update": cmd_domain_update,
    # KG Triples
    "triples": cmd_triples,
    "triple-search": cmd_triple_search,
    # KG Clusters
    "clusters": cmd_clusters,
    "cluster": cmd_cluster_get,
    # Attitude extended
    "attitude-history": cmd_attitude_history,
    # Skill history
    "skill-history": cmd_skill_history,
    # Frozen tier
    "frozen": cmd_frozen,
    "thaw": cmd_thaw,
    # Admin / Maintenance
    "status": cmd_status,
    "recalculate": cmd_recalculate,
    "decay": cmd_decay,
    "backfill": cmd_backfill,
    "sync-stats": cmd_sync_stats,
    "sync-scan": cmd_sync_scan,
    # Review round — missing commands
    "skill-proficiency": cmd_skill_proficiency,
    "triple-create": cmd_triple_create,
    "triple-delete": cmd_triple_delete,
    "attitude-create": cmd_attitude_create,
    "attitude-evolve": cmd_attitude_evolve,
    "attitude-delete": cmd_attitude_delete,
    "profile-upsert": cmd_profile_upsert,
    # Edge Invalidation + Entity Resolution + Graph Traversal
    "triple-invalidate": cmd_triple_invalidate,
    "entities": cmd_entities,
    "entity-stats": cmd_entity_stats,
    "entity-merge": cmd_entity_merge,
    "entity-merge-candidates": cmd_entity_merge_candidates,
    "entity-backfill": cmd_entity_backfill,
    "entity-auto-merge": cmd_entity_auto_merge,
    "traverse": cmd_traverse,
    # Flywheel bridge
    "session-context": cmd_session_context,
    "intelligence-ingest": cmd_intelligence_ingest,
}


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Build client with overrides (--api-url flag > MEMVAULT_API_URL env > SDK default)
    api_url = args.api_url or os.environ.get("MEMVAULT_API_URL") or None
    client = MemvaultClient(base_url=api_url)

    handler = COMMAND_MAP.get(args.command)
    if not handler:
        parser.print_help()
        sys.exit(1)

    try:
        handler(client, args)
    except APIConnectionError as e:
        print(f"  {e}", file=sys.stderr)
        sys.exit(1)
    except APIError as e:
        print(f"  {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
