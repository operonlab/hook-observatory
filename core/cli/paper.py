#!/Users/joneshong/.local/bin/python3
"""Paper CLI — academic paper management, digests, and annotations.

Usage:
    paper articles list [--category C] [--tag T] [--relevance R] [--cannibalize] [--limit N]
    paper articles get <id>
    paper articles search <query> [--limit N]
    paper articles create --title T [--abstract A] [--arxiv-id X] [--tags t1,t2]
    paper digest <id>
    paper digest generate <id> [--model M] [--force]
    paper annotate <id> --note "..." [--type highlight]
    paper dashboard
    paper fetch <arxiv-url-or-id>
    paper redigest --model M [--relevance high]
    paper status

Symlink: ln -sf ~/workshop/core/cli/paper.py ~/.local/bin/paper
"""

import argparse
import sys

from cli.cli_helpers import json_out, err, fmt_date
from cli.cli_utils import resolve_text_arg
from workshop.clients._base import APIConnectionError, APIError
from workshop.clients.paper import PaperClient


def cmd_articles_list(args):
    client = PaperClient()
    try:
        result = client.list_articles(
            page=args.page,
            page_size=args.limit,
            category=args.category,
            tag=args.tag,
            relevance=args.relevance,
            cannibalize_candidate=args.cannibalize_candidate,
        )
        if args.json:
            _json_out(result, True)
            return
        items = result.get("items", [])
        total = result.get("total", 0)
        print(f"Articles ({len(items)} of {total}):\n")
        for a in items:
            year = a.get("year", "?")
            cats = ", ".join((a.get("categories") or [])[:2])
            print(f"  [{year}] {a.get('title', '?')[:60]}")
            if cats:
                print(f"           categories: {cats}")
            print(f"           id={a.get('id', '?')}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_articles_get(args):
    client = PaperClient()
    try:
        a = client.get_article(args.id)
        if args.json:
            _json_out(a, True)
            return
        print(f"Title: {a.get('title', '?')}")
        authors = a.get("authors") or []
        print(f"Authors: {', '.join(str(x) for x in authors)}")
        print(f"Year: {a.get('year', '?')}")
        arxiv = a.get("arxiv_id")
        if arxiv:
            print(f"arXiv: {arxiv}")
        doi = a.get("doi")
        if doi:
            print(f"DOI: {doi}")
        cats = ", ".join(a.get("categories") or [])
        if cats:
            print(f"Categories: {cats}")
        tags = ", ".join(a.get("tags") or [])
        if tags:
            print(f"Tags: {tags}")
        print(f"\nAbstract:\n{a.get('abstract', '')[:2000]}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_articles_search(args):
    client = PaperClient()
    try:
        results = client.search(args.query, limit=args.limit)
        if args.json:
            _json_out(results, True)
            return
        items = results if isinstance(results, list) else results.get("items", [])
        if not items:
            print("No results found.")
            return
        print(f"Search results for '{args.query}':\n")
        for r in items:
            score = r.get("score", r.get("similarity", 0))
            print(f"  [{score:.3f}] {r.get('title', '?')[:60]}")
            print(f"           id={r.get('id', r.get('article_id', '?'))}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_articles_create(args):
    client = PaperClient()
    try:
        abstract = resolve_text_arg(args.abstract)
        tags = [t.strip() for t in args.tags.split(",")] if args.tags else []
        categories = [c.strip() for c in args.categories.split(",")] if args.categories else []
        authors = [a.strip() for a in args.authors.split(",")] if args.authors else []
        result = client.create_article(
            title=args.title,
            abstract=abstract,
            arxiv_id=args.arxiv_id,
            doi=args.doi,
            year=args.year,
            authors=authors or None,
            journal=args.journal,
            categories=categories or None,
            tags=tags or None,
        )
        if args.json:
            _json_out(result, True)
            return
        print(f"Article created: {result.get('id', '?')}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_digest(args):
    client = PaperClient()
    try:
        d = client.get_digest(args.id)
        if args.json:
            _json_out(d, True)
            return
        print(f"One-liner: {d.get('one_liner', '-')}")
        print(f"Relevance: {d.get('workshop_relevance', '?')}")
        print(f"Confidence: {d.get('confidence', '?')}")
        print(f"Model: {d.get('model_used', '?')}")
        print(f"Generated: {str(d.get('generated_at', ''))[:19]}")
        findings = d.get("key_findings", [])
        if findings:
            print("\nKey Findings:")
            for i, f in enumerate(findings, 1):
                print(f"  {i}. {f}")
        insight = d.get("actionable_insight")
        if insight:
            print(f"\nActionable Insight: {insight}")
        modules = d.get("applicable_modules", [])
        if modules:
            print(f"Applicable Modules: {', '.join(modules)}")
        effort = d.get("effort_estimate")
        if effort:
            print(f"Effort Estimate: {effort}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_digest_generate(args):
    client = PaperClient()
    try:
        d = client.trigger_digest(
            args.id,
            model_name=getattr(args, "model", None),
            force=getattr(args, "force", False),
        )
        if args.json:
            _json_out(d, True)
            return
        print(f"Digest generated for article {args.id}")
        print(f"  Relevance: {d.get('workshop_relevance', '?')}")
        print(f"  One-liner: {d.get('one_liner', '-')}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_annotate(args):
    client = PaperClient()
    try:
        note = resolve_text_arg(args.note)
        tags = [t.strip() for t in args.tags.split(",")] if args.tags else None
        result = client.create_annotation(
            article_id=args.id,
            note=note,
            annotation_type=args.type,
            tags=tags,
        )
        if args.json:
            _json_out(result, True)
            return
        print(f"Annotation created: {result.get('id', '?')}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_dashboard(args):
    client = PaperClient()
    try:
        d = client.get_dashboard()
        if args.json:
            _json_out(d, True)
            return
        print("Paper Dashboard")
        print("=" * 40)
        for k, v in d.items():
            print(f"  {k}: {v}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_fetch(args):
    client = PaperClient()
    try:
        result = client.fetch_arxiv(args.target)
        if args.json:
            _json_out(result, True)
            return
        print(f"Fetched: {result.get('title', '?')}")
        print(f"  id={result.get('id', '?')}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_redigest(args):
    client = PaperClient()
    try:
        result = client.redigest(model_name=args.model, relevance_filter=args.relevance)
        if args.json:
            _json_out(result, True)
            return
        count = result.get("processed", 0)
        print(f"Re-digested {count} articles.")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_status(args):
    client = PaperClient()
    try:
        s = client.status()
        _json_out(s, args.json)
        if not args.json:
            print(f"Status: {s.get('status', 'unknown')}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="paper",
        description="Paper — academic paper management CLI",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    # articles
    p_articles = sub.add_parser("articles", help="Article management")
    asub = p_articles.add_subparsers(dest="articles_cmd", required=True)

    p_alist = asub.add_parser("list", help="List articles")
    p_alist.add_argument("--category", help="Filter by category (e.g. cs.AI)")
    p_alist.add_argument("--tag", help="Filter by tag")
    p_alist.add_argument("--relevance", help="Filter by relevance (high/medium/low)")
    p_alist.add_argument("--cannibalize-candidate", action="store_true", default=None,
                         help="Show only cannibalize candidates")
    p_alist.add_argument("--limit", type=int, default=20)
    p_alist.add_argument("--page", type=int, default=1)
    p_alist.set_defaults(func=cmd_articles_list)

    p_aget = asub.add_parser("get", help="Get article by ID")
    p_aget.add_argument("id", help="Article ID")
    p_aget.set_defaults(func=cmd_articles_get)

    p_asearch = asub.add_parser("search", help="Semantic search")
    p_asearch.add_argument("query", help="Search query")
    p_asearch.add_argument("--limit", type=int, default=5)
    p_asearch.set_defaults(func=cmd_articles_search)

    p_acreate = asub.add_parser("create", help="Create a new article")
    p_acreate.add_argument("--title", required=True, help="Article title")
    p_acreate.add_argument("--abstract", help="Article abstract")
    p_acreate.add_argument("--arxiv-id", help="arXiv identifier")
    p_acreate.add_argument("--doi", help="DOI")
    p_acreate.add_argument("--year", type=int, help="Publication year")
    p_acreate.add_argument("--authors", help="Comma-separated author names")
    p_acreate.add_argument("--journal", help="Journal name")
    p_acreate.add_argument("--categories", help="Comma-separated categories (e.g. cs.AI,cs.CL)")
    p_acreate.add_argument("--tags", help="Comma-separated tags")
    p_acreate.set_defaults(func=cmd_articles_create)

    # digest
    p_digest = sub.add_parser("digest", help="Digest management")
    dsub = p_digest.add_subparsers(dest="digest_cmd")

    p_dget = dsub.add_parser("get", help="Get digest for article")
    p_dget.add_argument("id", help="Article ID")
    p_dget.set_defaults(func=cmd_digest)

    p_dgen = dsub.add_parser("generate", help="Generate digest for article")
    p_dgen.add_argument("id", help="Article ID")
    p_dgen.add_argument("--model", help="Override LLM model for digest generation")
    p_dgen.add_argument("--force", action="store_true", help="Regenerate even if digest exists")
    p_dgen.set_defaults(func=cmd_digest_generate)

    # Direct: paper digest <id> → get digest
    p_digest.add_argument("id", nargs="?", help="Article ID (shorthand for get)")
    p_digest.set_defaults(func=cmd_digest)

    # annotate
    p_annotate = sub.add_parser("annotate", help="Add annotation to article")
    p_annotate.add_argument("id", help="Article ID")
    p_annotate.add_argument("--note", required=True, help="Annotation text")
    p_annotate.add_argument(
        "--type",
        default="note",
        choices=["note", "highlight", "question", "synthesis", "action-taken"],
        help="Annotation type (default: note)",
    )
    p_annotate.add_argument("--tags", help="Comma-separated tags")
    p_annotate.set_defaults(func=cmd_annotate)

    # dashboard
    p_dash = sub.add_parser("dashboard", help="Dashboard summary")
    p_dash.set_defaults(func=cmd_dashboard)

    # fetch
    p_fetch = sub.add_parser("fetch", help="Fetch and import a paper from arXiv")
    p_fetch.add_argument("target", help="arXiv URL or bare ID (e.g. 2401.12345)")
    p_fetch.set_defaults(func=cmd_fetch)

    # redigest
    p_redigest = sub.add_parser("redigest", help="Batch re-generate digests")
    p_redigest.add_argument("--model", required=True, help="LLM model name to use")
    p_redigest.add_argument("--relevance", help="Filter by relevance (high/medium/low)")
    p_redigest.set_defaults(func=cmd_redigest)

    # status
    p_status = sub.add_parser("status", help="Module status")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
