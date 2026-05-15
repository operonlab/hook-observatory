"""CLI entry point: `python -m obsidian_sync sync --vault <path> --space <id> [...]`."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path

from .docvault_adapter import DocvaultAdapter, UploadResult
from .state import State
from .walker import compute_hash, walk_vault


def _build_tags(rel_path: str, vault_label: str) -> list[str]:
    top = rel_path.split("/", 1)[0]
    tags = ["obsidian", vault_label]
    if top and not top.endswith(".md"):
        tags.append(top)
    return tags


def _iter_planned(
    vault_path: Path,
    state: State,
    *,
    limit: int | None,
) -> Iterable[tuple[Path, str, str, str]]:
    seen = 0
    for md_path in walk_vault(vault_path):
        rel = md_path.relative_to(vault_path).as_posix()
        h = compute_hash(md_path)
        action = "upload" if state.is_changed(rel, h) else "skip"
        yield md_path, rel, h, action
        if action != "skip":
            seen += 1
            if limit is not None and seen >= limit:
                return


def cmd_sync(args: argparse.Namespace) -> int:
    vault_path = Path(args.vault).resolve()
    state_path = Path(args.state_file).expanduser()
    state = State.load(state_path, vault_path=vault_path, space_id=args.space)
    failed_log = Path(args.failed_log).expanduser() if args.failed_log else None

    if args.dry_run:
        rows = 0
        upload_rows = 0
        for md_path, rel, h, action in _iter_planned(vault_path, state, limit=args.limit):
            rows += 1
            if action != "skip":
                upload_rows += 1
            print(f"{action:<7} {h} {rel}")
        print(
            f"\n[dry-run] vault={vault_path} space={args.space} "
            f"total_listed={rows} will_upload={upload_rows}",
            file=sys.stderr,
        )
        return 0

    adapter = DocvaultAdapter(space_id=args.space, timeout=args.timeout)
    counts = {"uploaded": 0, "duplicate": 0, "timeout": 0, "error": 0, "skipped": 0}

    for md_path, rel, h, action in _iter_planned(vault_path, state, limit=args.limit):
        if action == "skip":
            counts["skipped"] += 1
            continue
        base_tags = _build_tags(rel, vault_label=args.vault_label)
        result: UploadResult = adapter.upload_markdown(
            file_path=md_path,
            vault=args.vault_label,
            rel_path=rel,
            base_tags=base_tags,
        )
        if result.status == "timeout":
            # Server typically commits the Document row before the client hits its
            # HTTP timeout (indexing happens after commit). A single retry usually
            # hits the dedup gate and lets us record the doc_id this run instead of
            # next run.
            retry: UploadResult = adapter.upload_markdown(
                file_path=md_path,
                vault=args.vault_label,
                rel_path=rel,
                base_tags=base_tags,
            )
            if retry.status in ("duplicate", "uploaded"):
                counts["timeout_recovered"] = counts.get("timeout_recovered", 0) + 1
                result = retry
        counts[result.status] = counts.get(result.status, 0) + 1
        if result.status in ("uploaded", "duplicate"):
            doc_id = result.document_id or f"server-dedup:{h}"
            state.record(rel, h, doc_id)
            # Phase 3: optionally tell memvault to supersede stale blocks now
            # that this doc carries the canonical version. Best-effort —
            # supersede failures must never fail the sync.
            if (
                args.supersede_memvault
                and result.status == "uploaded"
                and result.document_id
            ):
                meta_title = Path(rel).stem
                superseded = _fire_supersede(
                    doc_id=result.document_id,
                    query_text=f"{meta_title}\n{args.vault_label}\n{rel}",
                    memvault_space=args.supersede_memvault_space,
                    threshold=args.supersede_threshold,
                    dry_run=args.supersede_dry_run,
                )
                if superseded is not None:
                    n = len(superseded)
                    counts["supersede_matches" if args.supersede_dry_run else "superseded"] = (
                        counts.get(
                            "supersede_matches" if args.supersede_dry_run else "superseded",
                            0,
                        )
                        + n
                    )
                    if n:
                        tag = "dry" if args.supersede_dry_run else "live"
                        print(f"  supersede[{tag}] {n} memvault block(s) by doc={result.document_id[:8]}")
        else:
            print(f"FAIL {rel}: status={result.status} {result.error or result.skipped_reason}", file=sys.stderr)
            if failed_log:
                failed_log.parent.mkdir(parents=True, exist_ok=True)
                with failed_log.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"rel_path": rel, "status": result.status, "error": result.error, "skipped_reason": result.skipped_reason}) + "\n")
        print(f"{result.status:<10} {rel}")

    if args.reconcile:
        current = {Path(p).relative_to(vault_path).as_posix() for p in walk_vault(vault_path)}
        for rel in sorted(state.known_rel_paths() - current):
            doc_id = state.forget(rel)
            if doc_id and adapter.delete_document(doc_id):
                counts["deleted"] = counts.get("deleted", 0) + 1
                print(f"deleted    {rel}")

    state.save()
    print(f"\n[done] {counts}", file=sys.stderr)
    return 0 if counts.get("error", 0) == 0 else 2


def _fire_supersede(
    *,
    doc_id: str,
    query_text: str,
    memvault_space: str,
    threshold: float,
    dry_run: bool,
) -> list[str] | None:
    """Best-effort call to POST /api/memvault/supersede-by-doc.

    Returns the list of (would-be) superseded block_ids, or None on error.
    Never raises — supersede must not fail the sync.
    """
    import os
    import urllib.error
    import urllib.request

    body = json.dumps(
        {
            "doc_id": doc_id,
            "query_text": query_text[:4000],
            "threshold": threshold,
            "dry_run": dry_run,
        }
    ).encode("utf-8")
    url = f"http://127.0.0.1:10000/api/memvault/supersede-by-doc?space_id={memvault_space}"
    headers = {"Content-Type": "application/json"}
    key = os.environ.get("CORE_INTERNAL_API_KEY", "")
    if key:
        headers["X-Internal-Key"] = key
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
            if dry_run:
                return [m["block_id"] for m in data.get("dry_run_matches", [])]
            return list(data.get("superseded", []))
    except Exception as exc:
        print(f"  supersede error: {str(exc)[:160]}", file=sys.stderr)
        return None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="obsidian_sync")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("sync", help="Sync a vault folder into docvault")
    s.add_argument("--vault", required=True, help="Absolute path to the Obsidian vault root")
    s.add_argument("--space", required=True, help="Target docvault space_id (e.g. obsidian-blog)")
    s.add_argument(
        "--vault-label",
        default=None,
        help="Tag label for this vault (default: basename of --vault)",
    )
    s.add_argument("--state-file", required=True, help="Path to per-vault state.json")
    s.add_argument("--failed-log", default=None, help="Path to failed.jsonl (append-only)")
    s.add_argument("--dry-run", action="store_true", help="List planned actions without uploading")
    s.add_argument(
        "--reconcile",
        action="store_true",
        help="After upload pass, delete docvault docs whose source .md no longer exists",
    )
    s.add_argument("--limit", type=int, default=None, help="Max files to upload this run")
    s.add_argument("--timeout", type=float, default=300.0, help="Per-upload HTTP timeout seconds")
    # Phase 3: optional supersede-memvault hook after a successful upload.
    s.add_argument(
        "--supersede-memvault",
        action="store_true",
        help="After each upload, ask memvault to supersede stale blocks above similarity threshold",
    )
    s.add_argument(
        "--supersede-memvault-space",
        default="default",
        help="memvault space_id to scan (default: default — memvault uses caller space, not the docvault space)",
    )
    s.add_argument(
        "--supersede-threshold",
        type=float,
        default=0.85,
        help="Cosine similarity threshold for supersede (0.5–1.0; default 0.85, higher = stricter)",
    )
    s.add_argument(
        "--supersede-dry-run",
        action="store_true",
        help="With --supersede-memvault, only list candidates — do not invalidate any blocks",
    )
    s.set_defaults(func=cmd_sync)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.vault_label is None:
        args.vault_label = Path(args.vault).resolve().name
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
