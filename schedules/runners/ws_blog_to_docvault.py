#!/usr/bin/env python3
"""
ws_blog_to_docvault.py — Daily 08:30: sync Obsidian/blog vault to docvault

Incremental sync: only uploads changed/new .md files since last run.
State persisted at ~/workshop/outputs/obsidian-sync/state-blog.json

Env vars:
  OBSIDIAN_SYNC_DRY_RUN=1    — list planned actions, no upload
  OBSIDIAN_SYNC_LIMIT=N      — cap uploads at N files this run
  OBSIDIAN_SYNC_RECONCILE=1  — delete docvault docs whose source .md no longer exists

Logs: ~/workshop/outputs/obsidian-sync/logs/blog-sync.log
"""

import os
import sys
from datetime import datetime
from pathlib import Path

HOME = Path.home()

LOG_DIR = HOME / "workshop" / "outputs" / "obsidian-sync" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "blog-sync.log"

STATE_FILE = HOME / "workshop" / "outputs" / "obsidian-sync" / "state-blog.json"
FAILED_LOG = HOME / "workshop" / "outputs" / "obsidian-sync" / "failed-blog.jsonl"
VAULT = HOME / "Obsidian" / "blog"

# Ensure lib paths are available regardless of cwd (Cronicle may run from ~)
_WORKTREE_ROOT = Path(__file__).resolve().parents[2]  # .worktrees/feature/.../
sys.path.insert(0, str(_WORKTREE_ROOT / "libs" / "obsidian-sync"))
sys.path.insert(0, str(_WORKTREE_ROOT / "libs" / "sdk-client"))
# Fallback: ~/workshop paths (production install)
sys.path.insert(0, str(HOME / "workshop" / "libs" / "obsidian-sync"))
sys.path.insert(0, str(HOME / "workshop" / "libs" / "sdk-client"))


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main() -> int:
    log("=== ws_blog_to_docvault start ===")
    log(f"vault={VAULT}  state={STATE_FILE}")

    # Build argv for obsidian_sync.cli.main
    argv = [
        "sync",
        "--vault", str(VAULT),
        "--space", "obsidian-blog",
        "--vault-label", "blog",
        "--state-file", str(STATE_FILE),
        "--failed-log", str(FAILED_LOG),
    ]

    limit_env = os.getenv("OBSIDIAN_SYNC_LIMIT")
    if limit_env:
        argv += ["--limit", limit_env]

    if os.getenv("OBSIDIAN_SYNC_DRY_RUN") == "1":
        argv.append("--dry-run")

    if os.getenv("OBSIDIAN_SYNC_RECONCILE") == "1":
        argv.append("--reconcile")

    log(f"argv={argv}")

    try:
        from obsidian_sync.cli import main as cli_main

        exit_code = cli_main(argv)
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else 1

    if exit_code == 0:
        log("=== ws_blog_to_docvault OK ===")
    else:
        log(f"=== ws_blog_to_docvault FAILED exit_code={exit_code} ===")

    return exit_code or 0


if __name__ == "__main__":
    sys.exit(main())
