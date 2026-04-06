#!/Users/joneshong/.local/bin/python3
"""DocVault CLI — Command-line interface for the DocVault document knowledge system.

Uses the shared workshop SDK client.
Full coverage of document CRUD, QA, relations, coverage gaps, and stats.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from cli.cli_helpers import json_out
from cli.cli_utils import resolve_text_arg

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


def _print_document(doc: dict, verbose: bool = False) -> None:
    print(f"  📄 {doc.get('title', 'Untitled')}")
    status = doc.get("status", "?")
    stype = doc.get("source_type", "?")
    print(f"     ID: {doc['id']}  Status: {status}  Type: {stype}")
    if doc.get("tags"):
        print(f"     Tags: {fmt_tags(doc['tags'])}")
    if verbose:
        print(f"     Hash: {doc.get('content_hash', '?')[:16]}...")
        print(f"     Created: {fmt_dt(doc.get('created_at'))}")
        print(f"     Confidence: {doc.get('confidence', 0):.2f}")
        print(f"     Access count: {doc.get('access_count', 0)}")
    print()


def _print_qa_result(result: dict) -> None:
    print(f"\n💬 Answer (pipeline {result.get('pipeline_used', '?')}):\n")
    print(result.get("answer", "No answer"))
    print(f"\n  Confidence: {result.get('confidence', 0):.2f}")
    if result.get("crag_verdict"):
        print(f"  CRAG verdict: {result['crag_verdict']}")
    citations = result.get("citations", [])
    if citations:
        print(f"\n📎 Citations ({len(citations)}):")
        for i, c in enumerate(citations, 1):
            section = c.get("section", "")
            page = c.get("page", "")
            loc = f" (section: {section}, page: {page})" if section or page else ""
            print(f"  {i}. [{c.get('document_id', '?')}]{loc}")
            if c.get("quote"):
                print(f'     "{truncate(c["quote"], 120)}"')


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_upload(args) -> None:
    client = DocvaultClient()
    tags = [t.strip() for t in args.tags.split(",")] if args.tags else []
    try:
        doc = client.upload(args.file, args.title or Path(args.file).stem, tags=tags)
        if json_out(doc, args):
            return
        print("✅ Document uploaded:")
        _print_document(doc, verbose=True)
    except (APIError, APIConnectionError) as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)


def cmd_search(args) -> None:
    client = DocvaultClient()
    try:
        results = client.search(args.query, top_k=args.top_k, tag=args.tag)
        if json_out(results, args):
            return
        if not results:
            print("No results found.")
            return
        print(f"🔍 {len(results)} results:\n")
        for i, chunk in enumerate(results, 1):
            score = chunk.get("score", 0)
            content = truncate(chunk.get("content", ""), 200)
            meta = chunk.get("metadata", {})
            print(f"  {i}. [{score:.3f}] {meta.get('section_path', '')}")
            print(f"     {content}\n")
    except (APIError, APIConnectionError) as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)


def cmd_qa(args) -> None:
    client = DocvaultClient()
    question = resolve_text_arg(args.question) or args.question
    try:
        result = client.qa(question, mode=args.mode, top_k=args.top_k, domain=args.domain)
        if json_out(result, args):
            return
        _print_qa_result(result)
    except (APIError, APIConnectionError) as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)


def cmd_list(args) -> None:
    client = DocvaultClient()
    try:
        data = client.list_documents(
            page=args.page, page_size=args.page_size, status=args.status, tag=args.tag
        )
        if json_out(data, args):
            return
        items = data.get("items", [])
        total = data.get("total", 0)
        print(f"📚 Documents ({total} total, page {args.page}):\n")
        for doc in items:
            _print_document(doc)
    except (APIError, APIConnectionError) as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)


def cmd_info(args) -> None:
    client = DocvaultClient()
    try:
        doc = client.get_document(args.doc_id)
        if json_out(doc, args):
            return
        _print_document(doc, verbose=True)

        versions = client.list_versions(args.doc_id)
        if versions:
            print(f"  📋 Versions ({len(versions)}):")
            for v in versions:
                print(
                    f"     v{v.get('version_number', '?')} — {v.get('status', '?')} "
                    f"({v.get('chunk_count', 0)} chunks, {fmt_dt(v.get('created_at'))})"
                )
                if v.get("summary"):
                    print(f"       Summary: {truncate(v['summary'], 120)}")
    except (APIError, APIConnectionError) as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)


def cmd_supersede(args) -> None:
    client = DocvaultClient()
    try:
        version = client.supersede_document(args.doc_id, args.file)
        if json_out(version, args):
            return
        print(f"✅ New version created: v{version.get('version_number', '?')}")
        print(f"   Status: {version.get('status', '?')}")
    except (APIError, APIConnectionError) as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)


def cmd_relations(args) -> None:
    client = DocvaultClient()
    try:
        relations = client.list_relations(args.doc_id)
        if json_out(relations, args):
            return
        if not relations:
            print("No relations found.")
            return
        print(f"🔗 Relations ({len(relations)}):\n")
        for r in relations:
            src = r.get("source_document_id", "?")[:8]
            tgt = r.get("target_document_id", "?")[:8]
            rtype = r.get("relation_type", "?")
            conf = r.get("confidence", 0)
            print(f"  {src}.. —[{rtype}]→ {tgt}.. (conf={conf:.2f})")
            if r.get("evidence"):
                print(f"    Evidence: {truncate(r['evidence'], 100)}")
    except (APIError, APIConnectionError) as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)


def cmd_contradictions(args) -> None:
    client = DocvaultClient()
    try:
        results = client.find_contradictions()
        if json_out(results, args):
            return
        if not results:
            print("No contradictions detected.")
            return
        print(f"⚠️  Contradictions ({len(results)}):\n")
        for c in results:
            src = c.get("source_document_id", "?")[:8]
            tgt = c.get("target_document_id", "?")[:8]
            print(f"  {src}.. ↔ {tgt}..")
            if c.get("evidence"):
                print(f"    {truncate(c['evidence'], 120)}")
            print()
    except (APIError, APIConnectionError) as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)


def cmd_gaps(args) -> None:
    client = DocvaultClient()
    try:
        data = client.list_gaps(status=args.status)
        if json_out(data, args):
            return
        items = data.get("items", [])
        total = data.get("total", 0)
        print(f"🕳️  Coverage gaps ({total} total):\n")
        for g in items:
            status = g.get("status", "?")
            gap_type = g.get("gap_type", "?")
            print(f"  [{status}] {gap_type}: {truncate(g.get('query_text', ''), 120)}")
            if g.get("suggested_sources"):
                sug = json.dumps(g["suggested_sources"], ensure_ascii=False)[:100]
                print(f"    Suggestions: {sug}")
            print()
    except (APIError, APIConnectionError) as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)


def cmd_reindex(args) -> None:
    client = DocvaultClient()
    try:
        result = client.reindex(args.doc_id)
        if json_out(result, args):
            return
        print(f"✅ Re-index queued for document {args.doc_id}")
    except (APIError, APIConnectionError) as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)


def cmd_bulk_import(args) -> None:
    client = DocvaultClient()
    directory = Path(args.directory)
    if not directory.is_dir():
        print(f"❌ Not a directory: {args.directory}", file=sys.stderr)
        sys.exit(1)

    extensions = {".pdf", ".docx", ".md", ".txt"}
    files = [str(f) for f in directory.iterdir() if f.suffix.lower() in extensions]

    if not files:
        print("No supported files found (.pdf, .docx, .md, .txt)")
        return

    print(f"📦 Importing {len(files)} files from {args.directory}...\n")
    try:
        results = client.bulk_import(files)
        if json_out(results, args):
            return
        success = sum(1 for r in results if r["status"] == "success")
        errors = sum(1 for r in results if r["status"] == "error")
        print(f"  ✅ {success} imported, ❌ {errors} failed")
        for r in results:
            if r["status"] == "error":
                print(f"  ❌ {Path(r['file']).name}: {r['error']}")
    except (APIError, APIConnectionError) as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)


def cmd_stats(args) -> None:
    client = DocvaultClient()
    try:
        data = client.stats()
        if json_out(data, args):
            return
        print("📊 DocVault Statistics:\n")
        print(f"  Documents:  {data.get('total_documents', 0)}")
        print(f"  Chunks:     {data.get('total_chunks', 0)}")
        print(f"  Relations:  {data.get('total_relations', 0)}")
        print(f"  Gaps:       {data.get('total_gaps', 0)}")
        print(f"  QA logs:    {data.get('total_qa_logs', 0)}")
        if data.get("by_status"):
            print("\n  By status:")
            for s, c in data["by_status"].items():
                print(f"    {s}: {c}")
        if data.get("by_source_type"):
            print("\n  By source type:")
            for t, c in data["by_source_type"].items():
                print(f"    {t}: {c}")
    except (APIError, APIConnectionError) as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="docvault", description="DocVault document knowledge CLI")
    p.add_argument("--json", action="store_true", default=False, help="JSON output")
    sub = p.add_subparsers(dest="command")

    # upload
    up = sub.add_parser("upload", help="Upload a document")
    up.add_argument("file", help="Path to document file")
    up.add_argument("--title", help="Document title (default: filename)")
    up.add_argument("--tags", help="Comma-separated tags")

    # search
    se = sub.add_parser("search", help="Semantic search across documents")
    se.add_argument("query", help="Search query")
    se.add_argument("--top-k", type=int, default=5, dest="top_k")
    se.add_argument("--tag", help="Filter by tag")

    # qa
    qa = sub.add_parser("qa", help="Ask a question (Pipeline A/C)")
    qa.add_argument("question", help="Question text (use '-' for stdin, '@file' for file)")
    qa.add_argument("--mode", default="factual", choices=["factual", "mixed"])
    qa.add_argument("--top-k", type=int, default=5, dest="top_k")
    qa.add_argument("--domain", default="default")

    # list
    ls = sub.add_parser("list", help="List documents")
    ls.add_argument("--page", type=int, default=1)
    ls.add_argument("--page-size", type=int, default=20, dest="page_size")
    ls.add_argument("--status", help="Filter by status")
    ls.add_argument("--tag", help="Filter by tag")

    # info
    info = sub.add_parser("info", help="Document details + version history")
    info.add_argument("doc_id", help="Document ID")

    # supersede
    ss = sub.add_parser("supersede", help="Upload new version of a document")
    ss.add_argument("doc_id", help="Document ID")
    ss.add_argument("file", help="Path to new version file")

    # relations
    rel = sub.add_parser("relations", help="View document relations")
    rel.add_argument("doc_id", help="Document ID")

    # contradictions
    sub.add_parser("contradictions", help="List contradicting document pairs")

    # gaps
    gp = sub.add_parser("gaps", help="List coverage gaps")
    gp.add_argument("--status", help="Filter by status")

    # reindex
    ri = sub.add_parser("reindex", help="Re-index a document")
    ri.add_argument("doc_id", help="Document ID")

    # bulk-import
    bi = sub.add_parser("bulk-import", help="Bulk import documents from a directory")
    bi.add_argument("directory", help="Directory containing documents")

    # stats
    sub.add_parser("stats", help="Statistics overview")

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    commands = {
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

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    handler = commands.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
