#!/usr/bin/env python3
"""Migrate mcp_config.json to use mcp-lazy-wrapper for on-demand servers.

Transforms command/args for on-demand servers to run through the lazy wrapper.
Creates a backup before modifying. Idempotent (skips already-wrapped servers).

Usage:
    python3 mcp-lazy-migrate.py              # preview changes (dry-run)
    python3 mcp-lazy-migrate.py --apply      # apply changes
    python3 mcp-lazy-migrate.py --revert     # revert to backup
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

CONFIG_PATH = Path.home() / ".mcpproxy" / "mcp_config.json"
WRAPPER_PATH = Path.home() / ".local" / "bin" / "mcp-lazy-wrapper"
MCP_DIR = Path.home() / "workshop" / "mcp"

IDLE_TIMEOUT = 1800  # 30 minutes

# Servers that should always stay on (no wrapper)
ALWAYS_ON = {
    "memvault",
    "taskflow",
    "sandbox-executor",
    "tmux-relay",
    "hook-observatory",
    "session-channel",
    "fleet",
    "capture",
}

# Marker to detect already-wrapped servers
WRAPPER_MARKER = "mcp-lazy-wrapper.py"


def wrap_server(server: dict) -> dict | None:
    """Transform a server entry to use the lazy wrapper.

    Returns modified server dict, or None if no change needed.
    """
    name = server.get("name", "")
    if name in ALWAYS_ON:
        return None
    if server.get("protocol") != "stdio":
        return None
    if not server.get("enabled", False):
        return None

    # Check if already wrapped
    args = server.get("args", [])
    for arg in args:
        if WRAPPER_MARKER in str(arg):
            return None

    # Build wrapped command
    original_cmd = server["command"]
    original_args = list(args)

    # Find tools_cache.json path
    cache_path = MCP_DIR / name / "tools_cache.json"
    cache_arg = str(cache_path) if cache_path.exists() else ""

    new_args = [
        "--idle-timeout",
        str(IDLE_TIMEOUT),
        "--name",
        name,
    ]
    if cache_arg:
        new_args.extend(["--tools-cache", cache_arg])
    new_args.append("--")
    new_args.append(original_cmd)
    new_args.extend(original_args)

    modified = dict(server)
    modified["command"] = str(WRAPPER_PATH)
    modified["args"] = new_args
    modified["updated"] = datetime.now().astimezone().isoformat()
    return modified


def unwrap_server(server: dict) -> dict | None:
    """Revert a wrapped server to its original command.

    Returns modified server dict, or None if not wrapped.
    """
    args = server.get("args", [])
    # Find the -- separator
    try:
        sep_idx = args.index("--")
    except ValueError:
        return None

    # Check if this is actually wrapped
    if not any(WRAPPER_MARKER in str(a) for a in args[:sep_idx]):
        return None

    original_cmd = args[sep_idx + 1] if len(args) > sep_idx + 1 else ""
    original_args = args[sep_idx + 2 :]

    modified = dict(server)
    modified["command"] = original_cmd
    modified["args"] = original_args
    modified["updated"] = datetime.now().astimezone().isoformat()
    return modified


def main():
    if not CONFIG_PATH.exists():
        print(f"Config not found: {CONFIG_PATH}")
        sys.exit(1)

    apply_mode = "--apply" in sys.argv
    revert_mode = "--revert" in sys.argv

    config = json.loads(CONFIG_PATH.read_text())
    servers = config.get("mcpServers", [])

    changes = []

    for i, server in enumerate(servers):
        name = server.get("name", "?")
        if revert_mode:
            modified = unwrap_server(server)
            if modified:
                changes.append((i, name, "unwrap", modified))
        else:
            modified = wrap_server(server)
            if modified:
                changes.append((i, name, "wrap", modified))

    if not changes:
        action = "revert" if revert_mode else "wrap"
        print(f"No servers to {action}.")
        return

    print(f"{'PREVIEW' if not apply_mode else 'APPLYING'} changes:\n")
    for idx, name, action, modified in changes:
        print(f"  [{action}] {name}")
        if action == "wrap":
            print(f"         cmd: {modified['command']}")
            # Show just the wrapper args (not the full path)
            wrapper_args = []
            for a in modified["args"]:
                if "--" == a:
                    break
                base = Path(a).name if "/" in a else a
                wrapper_args.append(base)
            print(f"         wrapper: {' '.join(wrapper_args)}")

    if not apply_mode:
        print(f"\n{len(changes)} servers would be modified.")
        print("Run with --apply to apply changes.")
        return

    # Backup
    backup_path = CONFIG_PATH.with_suffix(
        f".backup-{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    shutil.copy2(CONFIG_PATH, backup_path)
    print(f"\nBackup: {backup_path}")

    # Apply
    for idx, name, action, modified in changes:
        servers[idx] = modified

    config["mcpServers"] = servers
    CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False))
    print(f"Applied {len(changes)} changes to {CONFIG_PATH}")
    print("\nRestart mcpproxy to activate:")
    print("  mcpproxy daemon restart")


if __name__ == "__main__":
    main()
