#!/Users/joneshong/.local/bin/python3
"""Crawl4AI CLI — web crawling, chunking, URL filtering/scoring, HTML-to-Markdown.

Usage:
    crawl4ai crawl <url> [--timeout 60] [--json]
    crawl4ai chunk <text> [--file F] [--strategy sentence|regex|fixed|sliding]
                          [--size 1000] [--overlap 100] [--json]
    crawl4ai filter <url>... [--domains d1,d2] [--block-paths p1,p2] [--dedup] [--json]
    crawl4ai score <url>... [--keywords kw1,kw2] [--authority d=0.9] [--json]
    crawl4ai html2md [--file F | --stdin] [--citations] [--json]

Symlink: ln -sf ~/workshop/core/cli/crawl4ai_cli.py ~/.local/bin/crawl4ai
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

_CORE_SRC = str(Path(__file__).parents[1] / "src")
_LIBS_SRC = str(Path(__file__).parents[2] / "libs" / "python" / "src")


def _jout(data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _read_text(args: argparse.Namespace) -> str:
    if getattr(args, "file", None):
        return Path(args.file).read_text(encoding="utf-8")
    if getattr(args, "text", None):
        return args.text
    if not sys.stdin.isatty():
        return sys.stdin.read()
    print("Error: provide text argument, --file, or pipe via stdin.", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_crawl(args: argparse.Namespace) -> None:
    sys.path.insert(0, _LIBS_SRC)
    from sdk_client.crawl4ai_bridge import crawl_url

    try:
        r = asyncio.run(crawl_url(args.url, timeout=args.timeout))
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    if args.json:
        _jout(
            {
                "url": r.url,
                "title": r.title,
                "markdown": r.markdown,
                "links": r.links,
                "metadata": r.metadata,
                "success": r.success,
                "error": r.error,
            }
        )
        return
    if not r.success:
        print(f"Error: {r.error}", file=sys.stderr)
        sys.exit(1)
    if r.title:
        print(f"# {r.title}\n")
    print(r.markdown)
    if r.links:
        print(f"\n--- {len(r.links)} link(s) extracted ---")


def cmd_chunk(args: argparse.Namespace) -> None:
    sys.path.insert(0, _CORE_SRC)
    from shared.chunking import (
        FixedLengthChunking,
        RegexChunking,
        SentenceChunking,
        SlidingWindowChunking,
    )

    text = _read_text(args)
    chunker = {
        "sentence": lambda: SentenceChunking(),
        "regex": lambda: RegexChunking(),
        "fixed": lambda: FixedLengthChunking(chunk_size=args.size, overlap=args.overlap),
        "sliding": lambda: SlidingWindowChunking(window_size=args.size, step=args.overlap),
    }[args.strategy]()
    chunks = chunker.chunk(text)
    if args.json:
        _jout({"strategy": args.strategy, "count": len(chunks), "chunks": chunks})
        return
    print(f"Strategy: {args.strategy}  |  {len(chunks)} chunk(s)\n")
    for i, c in enumerate(chunks, 1):
        preview = c[:120].replace("\n", " ")
        print(f"[{i:>3}] {preview}{'…' if len(c) > 120 else ''}")


def cmd_filter(args: argparse.Namespace) -> None:
    sys.path.insert(0, _CORE_SRC)
    from shared.url_filter import DomainFilter, DuplicateFilter, FilterChain, PathPatternFilter

    filters = []
    if args.domains:
        filters.append(
            DomainFilter(allowed_domains=[d.strip() for d in args.domains.split(",") if d.strip()])
        )
    if args.block_paths:
        filters.append(
            PathPatternFilter(
                blocked_patterns=[p.strip() for p in args.block_paths.split(",") if p.strip()]
            )
        )
    if args.dedup:
        filters.append(DuplicateFilter())

    passed = FilterChain(filters=filters).apply_batch(args.urls)
    rejected = [u for u in args.urls if u not in passed]
    if args.json:
        _jout(
            {
                "total": len(args.urls),
                "passed": len(passed),
                "rejected": len(rejected),
                "urls": passed,
            }
        )
        return
    print(f"Filtered: {len(passed)}/{len(args.urls)} passed\n")
    for u in passed:
        print(f"  [PASS] {u}")
    for u in rejected:
        print(f"  [DROP] {u}")


def cmd_score(args: argparse.Namespace) -> None:
    sys.path.insert(0, _CORE_SRC)
    from shared.url_scorer import CompositeScorer, DomainAuthorityScorer, KeywordScorer

    scorers = []
    if args.keywords:
        scorers.append(
            KeywordScorer(
                keywords=[k.strip() for k in args.keywords.split(",") if k.strip()], weight=1.5
            )
        )
    if args.authority:
        ds: dict[str, float] = {}
        for pair in args.authority.split(","):
            if "=" in pair:
                d, s = pair.strip().split("=", 1)
                try:
                    ds[d.strip()] = float(s)
                except ValueError:
                    pass
        if ds:
            scorers.append(DomainAuthorityScorer(domain_scores=ds, weight=1.0))

    ranked = (
        CompositeScorer(scorers=scorers).rank(args.urls)
        if scorers
        else [(u, 0.5) for u in args.urls]
    )
    if args.json:
        _jout([{"url": u, "score": round(s, 4)} for u, s in ranked])
        return
    print(f"Scored {len(ranked)} URL(s):\n")
    for url, score in ranked:
        print(f"  {score:.3f} {'█' * int(score * 20):<20} {url}")


def cmd_html2md(args: argparse.Namespace) -> None:
    sys.path.insert(0, _CORE_SRC)
    from shared.markdown_gen import DefaultMarkdownGenerator

    if args.file:
        html_in = Path(args.file).read_text(encoding="utf-8")
    elif not sys.stdin.isatty():
        html_in = sys.stdin.read()
    else:
        print("Error: provide --file or pipe HTML via stdin.", file=sys.stderr)
        sys.exit(1)

    r = DefaultMarkdownGenerator().convert(html_in, links_as_citations=args.citations)
    if args.json:
        _jout({"title": r.title, "markdown": r.markdown, "links": r.links})
        return
    if r.title:
        print(f"# {r.title}\n")
    print(r.markdown)
    if args.citations and r.links:
        print("\n## References\n")
        for i, link in enumerate(r.links, 1):
            print(f"[{i}] {link}")


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(prog="crawl4ai", description="Crawl4AI CLI")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    # crawl
    p = sub.add_parser("crawl", help="Crawl a URL and output Markdown")
    p.add_argument("url")
    p.add_argument("--timeout", type=float, default=60.0, help="Timeout in seconds")
    p.set_defaults(func=cmd_crawl)

    # chunk
    p = sub.add_parser("chunk", help="Chunk text")
    p.add_argument("text", nargs="?", default=None, help="Text to chunk")
    p.add_argument("--file", "-f", help="Read from file")
    p.add_argument(
        "--strategy",
        choices=["sentence", "regex", "fixed", "sliding"],
        default="sentence",
        help="Chunking strategy",
    )
    p.add_argument("--size", type=int, default=1000, help="Chunk/window size")
    p.add_argument("--overlap", type=int, default=100, help="Overlap/step size")
    p.set_defaults(func=cmd_chunk)

    # filter
    p = sub.add_parser("filter", help="Filter URLs")
    p.add_argument("urls", nargs="+")
    p.add_argument("--domains", help="Comma-separated allowed domains")
    p.add_argument("--block-paths", help="Comma-separated path patterns to block")
    p.add_argument("--dedup", action="store_true", help="Deduplicate")
    p.set_defaults(func=cmd_filter)

    # score
    p = sub.add_parser("score", help="Score and rank URLs")
    p.add_argument("urls", nargs="+")
    p.add_argument("--keywords", help="Comma-separated keywords")
    p.add_argument("--authority", help='domain=score pairs, e.g. "github.com=0.9"')
    p.set_defaults(func=cmd_score)

    # html2md
    p = sub.add_parser("html2md", help="Convert HTML to Markdown")
    p.add_argument("--file", "-f", help="Read HTML from file")
    p.add_argument("--stdin", action="store_true", help="Read from stdin")
    p.add_argument("--citations", action="store_true", help="Links as [N] citations")
    p.set_defaults(func=cmd_html2md)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
