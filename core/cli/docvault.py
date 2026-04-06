#!/Users/joneshong/.local/bin/python3
"""DocVault CLI — Command-line interface for the DocVault document knowledge system.

Uses the shared workshop SDK client. 12 commands covering document
lifecycle, search, QA, relations, gaps, and management.
"""

import argparse
import os
import sys
from datetime import datetime

from cli.cli_helpers import json_out

from sdk_client._base import APIConnectionError, APIError
from sdk_client.docvault import DocvaultClient

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def truncate(text: str, length: int = 300) -> str:
    text = text.replace("\n", " ").strip()
    if len(text) <= length:
        return text
    return text[:length] + "..."


def fmt_dt(iso: str | None) -> str:
    if not iso:
        return "n/a"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, AttributeError):
        return str(iso)


def fmt_tags(tags: list[str]) -> str:
    if not tags:
        return ""
    return "[" + ", ".join(tags) + "]"


def _parse_tags(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [t.strip() for t in raw.split(",") if t.strip()]


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def cmd_upload(client: DocvaultClient, args: argparse.Namespace) -> None:
    """Upload a document."""
    tags = _parse_tags(args.tags)
    data = client.upload(
        file_path=args.file,
        title=args.title,
        source_type=args.source_type,
        source_uri=args.source_uri,
        tags=tags,
    )
    if json_out(data, args):
        return

    doc_id = data.get("id", "?")
    if args.quiet:
        print(doc_id)
    else:
        print(f"  Document uploaded: {doc_id}")
        print(f"  Title: {data.get('title', '?')}")
        print(f"  Type: {data.get('source_type', '?')}")


def cmd_search(client: DocvaultClient, args: argparse.Namespace) -> None:
    """Semantic search over document chunks."""
    tags = _parse_tags(args.tags)
    data = client.search(
        args.query,
        top_k=args.top_k,
        source_type=args.source_type,
        tags=tags,
    )
    if json_out(data, args):
        return

    results = data.get("results", data.get("chunks", []))
    if not results:
        if not args.quiet:
            print("  No results found.")
        return

    for i, item in enumerate(results, 1):
        score = item.get("score", 0)
        section = item.get("section_path", "")
        content = item.get("content", "")
        doc_id = item.get("document_id", "?")[:12]

        if args.quiet:
            print(f"{score:.1%} {truncate(content, 120)}")
        else:
            print(f"  {i}. [{score:.1%}] doc={doc_id} {section}")
            print(f"     {truncate(content)}")
            print()


def cmd_qa(client: DocvaultClient, args: argparse.Namespace) -> None:
    """Ask a question against the document corpus."""
    data = client.qa(
        args.question,
        mode=args.mode,
        domain=args.domain,
        top_k=args.top_k,
    )
    if json_out(data, args):
        return

    print(f"  Q: {args.question}")
    print()
    print(f"  A: {data.get('answer', 'No answer')}")
    print()

    citations = data.get("citations", [])
    if citations and not args.quiet:
        print("  Citations:")
        for c in citations:
            idx = c.get("index", "?")
            section = c.get("section", "?")
            page = c.get("page", "")
            page_info = f" p.{page}" if page else ""
            print(f"    [{idx}] {section}{page_info}")
        print()

    confidence = data.get("confidence")
    verdict = data.get("crag_verdict")
    if not args.quiet:
        parts = []
        if confidence is not None:
            parts.append(f"confidence={confidence:.2f}")
        if verdict:
            parts.append(f"verdict={verdict}")
        pipeline = data.get("pipeline_used", "?")
        parts.append(f"pipeline={pipeline}")
        print(f"  ({', '.join(parts)})")


def cmd_list(client: DocvaultClient, args: argparse.Namespace) -> None:
    """List documents."""
    data = client.list_documents(
        page=args.page,
        page_size=args.page_size,
        tag=args.tag,
        status=args.status,
    )
    if json_out(data, args):
        return

    items = data.get("items", [])
    total = data.get("total", "?")

    if not items:
        if not args.quiet:
            print("  No documents found.")
        return

    if not args.quiet:
        print(f"  Documents (page {args.page}, {total} total)")
        print("  " + "-" * 60)

    for d in items:
        did = d.get("id", "?")[:12]
        title = d.get("title", "?")
        status = d.get("status", "?")
        source = d.get("source_type", "?")
        tags = fmt_tags(d.get("tags", []))
        created = fmt_dt(d.get("created_at"))

        if args.quiet:
            print(f"{did} [{status}] {title}")
        else:
            print(f"  {did}  [{status}] ({source}) {title} {tags}")
            print(f"    Created: {created}")
            print()


def cmd_info(client: DocvaultClient, args: argparse.Namespace) -> None:
    """Get detailed document info."""
    data = client.get_document(args.document_id)
    if json_out(data, args):
        return

    if args.quiet:
        print(f"{data.get('title', '?')} [{data.get('status', '?')}]")
        return

    print(f"  ID          : {data.get('id', '?')}")
    print(f"  Title       : {data.get('title', '?')}")
    print(f"  Status      : {data.get('status', '?')}")
    print(f"  Source Type  : {data.get('source_type', '?')}")
    print(f"  Source URI   : {data.get('source_uri', 'n/a')}")
    print(f"  Content Hash : {data.get('content_hash', '?')}")
    print(f"  Tags         : {fmt_tags(data.get('tags', []))}")
    print(f"  Confidence   : {data.get('confidence', 'n/a')}")
    print(f"  Access Count : {data.get('access_count', 0)}")
    print(f"  Created      : {fmt_dt(data.get('created_at'))}")
    print(f"  Updated      : {fmt_dt(data.get('updated_at'))}")


def cmd_supersede(client: DocvaultClient, args: argparse.Namespace) -> None:
    """Mark a document as superseded."""
    data = client.supersede_document(
        args.document_id,
        args.new_document_id,
        reason=args.reason,
    )
    if json_out(data, args):
        return

    if args.quiet:
        print("ok")
    else:
        print(f"  Document {args.document_id[:12]} superseded by {args.new_document_id[:12]}")


def cmd_relations(client: DocvaultClient, args: argparse.Namespace) -> None:
    """List document relations."""
    data = client.list_relations(
        args.document_id,
        page=args.page,
        page_size=args.page_size,
    )
    if json_out(data, args):
        return

    items = data.get("items", [])
    if not items:
        if not args.quiet:
            print("  No relations found.")
        return

    for r in items:
        src = r.get("source_document_id", "?")[:12]
        tgt = r.get("target_document_id", "?")[:12]
        rtype = r.get("relation_type", "?")
        conf = r.get("confidence")

        if args.quiet:
            print(f"{src} --[{rtype}]--> {tgt}")
        else:
            conf_str = f" ({conf:.2f})" if conf is not None else ""
            print(f"  {src} --[{rtype}]--> {tgt}{conf_str}")
            evidence = r.get("evidence", "")
            if evidence:
                print(f"    Evidence: {truncate(evidence, 120)}")


def cmd_contradictions(client: DocvaultClient, args: argparse.Namespace) -> None:
    """Find contradictions across documents."""
    data = client.find_contradictions(
        document_id=args.document_id if hasattr(args, "document_id") and args.document_id else None,
    )
    if json_out(data, args):
        return

    items = data.get("contradictions", data.get("items", []))
    if not items:
        if not args.quiet:
            print("  No contradictions found.")
        return

    for c in items:
        src = c.get("source_document_id", c.get("document_a_id", "?"))[:12]
        tgt = c.get("target_document_id", c.get("document_b_id", "?"))[:12]
        ctype = c.get("type", c.get("contradiction_type", "?"))
        hint = c.get("resolution_hint", "")

        if args.quiet:
            print(f"{src} ↔ {tgt} [{ctype}]")
        else:
            print(f"  {src} ↔ {tgt} [{ctype}]")
            if hint:
                print(f"    Hint: {hint}")


def cmd_gaps(client: DocvaultClient, args: argparse.Namespace) -> None:
    """List coverage gaps."""
    data = client.list_gaps(
        page=args.page,
        page_size=args.page_size,
        status=args.status,
    )
    if json_out(data, args):
        return

    items = data.get("items", [])
    total = data.get("total", "?")

    if not items:
        if not args.quiet:
            print("  No coverage gaps found.")
        return

    if not args.quiet:
        print(f"  Coverage Gaps (page {args.page}, {total} total)")
        print("  " + "-" * 60)

    for g in items:
        gid = g.get("id", "?")[:12]
        query = g.get("query_text", "?")
        gap_type = g.get("gap_type", "?")
        status = g.get("status", "?")

        if args.quiet:
            print(f"{gid} [{status}] {truncate(query, 80)}")
        else:
            print(f"  {gid}  [{status}] ({gap_type})")
            print(f"    Query: {truncate(query, 150)}")
            detected = fmt_dt(g.get("detected_at"))
            print(f"    Detected: {detected}")
            print()


def cmd_reindex(client: DocvaultClient, args: argparse.Namespace) -> None:
    """Trigger reindexing."""
    doc_id = args.document_id if hasattr(args, "document_id") else None
    data = client.reindex(document_id=doc_id)
    if json_out(data, args):
        return

    if args.quiet:
        print("ok")
    else:
        scope = f"document {doc_id[:12]}" if doc_id else "all documents"
        print(f"  Reindex triggered for {scope}")


def cmd_bulk_import(client: DocvaultClient, args: argparse.Namespace) -> None:
    """Bulk import documents from a directory."""
    tags = _parse_tags(args.tags)
    data = client.bulk_import(
        args.source_dir,
        source_type=args.source_type,
        tags=tags,
    )
    if json_out(data, args):
        return

    imported = data.get("imported", 0)
    errors = data.get("errors", 0)

    if args.quiet:
        print(f"{imported} imported, {errors} errors")
    else:
        print(f"  Bulk import from: {args.source_dir}")
        print(f"  Imported: {imported}")
        print(f"  Errors: {errors}")


def cmd_stats(client: DocvaultClient, args: argparse.Namespace) -> None:
    """Display aggregate statistics."""
    data = client.stats()
    if json_out(data, args):
        return

    if args.quiet:
        print(
            f"docs={data.get('total_documents', '?')} "
            f"chunks={data.get('total_chunks', '?')} "
            f"qa={data.get('total_qa_logs', '?')}"
        )
        return

    print("  DocVault Statistics")
    print("  -------------------")
    print(f"  Documents     : {data.get('total_documents', '?')}")
    print(f"  Chunks        : {data.get('total_chunks', '?')}")
    print(f"  QA Logs       : {data.get('total_qa_logs', '?')}")
    print(f"  Coverage Gaps : {data.get('coverage_gap_count', '?')}")
    print(f"  Published     : {data.get('published_count', '?')}")

    recent = data.get("recent_documents", [])
    if recent:
        print()
        print("  Recent Documents:")
        for d in recent[:5]:
            title = d.get("title", "?")
            status = d.get("status", "?")
            created = fmt_dt(d.get("created_at"))
            print(f"    [{status}] {title} ({created})")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", dest="json_output", action="store_true", help="Output raw JSON")
    common.add_argument("--quiet", action="store_true", help="Minimal output")
    common.add_argument("--api-url", dest="api_url", default=None, help="Override Core API URL")

    paginated = argparse.ArgumentParser(add_help=False)
    paginated.add_argument("--page", type=int, default=1, help="Page number (default: 1)")
    paginated.add_argument("--page-size", type=int, default=20, help="Items per page (default: 20)")

    parser = argparse.ArgumentParser(
        prog="docvault",
        description="CLI for the DocVault document knowledge system",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # upload
    p = sub.add_parser("upload", parents=[common], help="Upload a document")
    p.add_argument("file", nargs="?", help="Path to document file")
    p.add_argument("--title", help="Document title (default: filename stem)")
    p.add_argument(
        "--source-type",
        default="markdown",
        choices=["pdf", "docx", "markdown", "webpage", "api"],
        help="Source type (default: markdown)",
    )
    p.add_argument("--source-uri", help="Source URI")
    p.add_argument("--tags", help="Comma-separated tags")

    # search
    p = sub.add_parser("search", parents=[common], help="Semantic search over documents")
    p.add_argument("query", help="Search query")
    p.add_argument("--top-k", type=int, default=10, help="Number of results (default: 10)")
    p.add_argument("--source-type", help="Filter by source type")
    p.add_argument("--tags", help="Comma-separated tag filter")

    # qa
    p = sub.add_parser("qa", parents=[common], help="Ask a question")
    p.add_argument("question", help="Question text")
    p.add_argument(
        "--mode",
        default="factual",
        choices=["factual", "mixed"],
        help="QA mode (default: factual)",
    )
    p.add_argument("--domain", default="default", help="Domain profile (default: default)")
    p.add_argument("--top-k", type=int, default=6, help="Evidence chunks (default: 6)")

    # list
    p = sub.add_parser("list", parents=[common, paginated], help="List documents")
    p.add_argument("--tag", help="Filter by tag")
    p.add_argument("--status", help="Filter by status")

    # info
    p = sub.add_parser("info", parents=[common], help="Get document info")
    p.add_argument("document_id", help="Document ID")

    # supersede
    p = sub.add_parser("supersede", parents=[common], help="Mark document as superseded")
    p.add_argument("document_id", help="Document ID to supersede")
    p.add_argument("new_document_id", help="Newer document ID")
    p.add_argument("--reason", help="Reason for superseding")

    # relations
    p = sub.add_parser("relations", parents=[common, paginated], help="List document relations")
    p.add_argument("document_id", help="Document ID")

    # contradictions
    p = sub.add_parser(
        "contradictions", parents=[common], help="Find contradictions across documents"
    )
    p.add_argument("--document-id", help="Filter by document ID")

    # gaps
    p = sub.add_parser("gaps", parents=[common, paginated], help="List coverage gaps")
    p.add_argument("--status", help="Filter by status (pending/investigating/resolved/dismissed)")

    # reindex
    p = sub.add_parser("reindex", parents=[common], help="Trigger reindexing")
    p.add_argument("--document-id", help="Reindex specific document (default: all)")

    # bulk-import
    p = sub.add_parser("bulk-import", parents=[common], help="Bulk import from directory")
    p.add_argument("source_dir", help="Directory containing documents")
    p.add_argument(
        "--source-type",
        default="markdown",
        choices=["pdf", "docx", "markdown"],
        help="Source type (default: markdown)",
    )
    p.add_argument("--tags", help="Comma-separated tags to apply")

    # stats
    sub.add_parser("stats", parents=[common], help="Display statistics")

    return parser


COMMAND_MAP: dict = {
    "upload": cmd_upload,
    "search": cmd_search,
    "qa": cmd_qa,
    "list": cmd_list,
    "info": cmd_info,
    "supersede": cmd_supersede,
    "relations": cmd_relations,
    "contradictions": cmd_contradictions,
    "gaps": cmd_gaps,
    "reindex": cmd_reindex,
    "bulk-import": cmd_bulk_import,
    "stats": cmd_stats,
}


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    api_url = args.api_url or os.environ.get("DOCVAULT_API_URL") or None
    client = DocvaultClient(base_url=api_url)

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
