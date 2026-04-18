#!/usr/bin/env python3
"""Generate tools_cache.json for each MCP server.

Spawns each server, sends initialize + tools/list, captures the tool list,
saves to mcp/<name>/tools_cache.json, then kills the server.

Usage:
    python3 mcp-lazy-warmup.py                    # all servers
    python3 mcp-lazy-warmup.py agent-metrics stt   # specific servers
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

MCP_DIR = Path(__file__).parent.parent / "mcp"
CONFIG_PATH = Path.home() / ".mcpproxy" / "mcp_config.json"

# Always-on servers (skip warmup, they don't need cache)
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


async def warmup_server(
    name: str, command: str, args: list[str], env: dict[str, str] | None = None
) -> list[dict] | None:
    """Spawn a server, get its tool list, then kill it."""
    import os

    full_env = {**os.environ}
    if env:
        full_env.update(env)

    cmd = [command] + args
    print(f"  [{name}] Spawning: {' '.join(cmd[:3])}...", flush=True)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=full_env,
        )
    except Exception as e:
        print(f"  [{name}] Failed to spawn: {e}", flush=True)
        return None

    try:
        # Send initialize
        init_req = (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "mcp-lazy-warmup", "version": "1.0.0"},
                    },
                }
            )
            + "\n"
        )
        proc.stdin.write(init_req.encode("utf-8"))
        await proc.stdin.drain()

        # Read initialize response
        line = await asyncio.wait_for(proc.stdout.readline(), timeout=15)
        if not line:
            print(f"  [{name}] No response to initialize", flush=True)
            return None

        # Send initialized notification
        notif = (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                }
            )
            + "\n"
        )
        proc.stdin.write(notif.encode("utf-8"))
        await proc.stdin.drain()

        # Send tools/list
        tools_req = (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                }
            )
            + "\n"
        )
        proc.stdin.write(tools_req.encode("utf-8"))
        await proc.stdin.drain()

        # Read tools/list response
        line = await asyncio.wait_for(proc.stdout.readline(), timeout=15)
        if not line:
            print(f"  [{name}] No response to tools/list", flush=True)
            return None

        msg = json.loads(line.decode("utf-8"))
        tools = msg.get("result", {}).get("tools", [])
        return tools

    except TimeoutError:
        print(f"  [{name}] Timeout", flush=True)
        return None
    except Exception as e:
        print(f"  [{name}] Error: {e}", flush=True)
        return None
    finally:
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


async def main():
    if not CONFIG_PATH.exists():
        print(f"Config not found: {CONFIG_PATH}")
        sys.exit(1)

    config = json.loads(CONFIG_PATH.read_text())
    servers = config.get("mcpServers", [])

    # Filter by CLI args if provided
    filter_names = set(sys.argv[1:]) if len(sys.argv) > 1 else None

    success = 0
    skipped = 0
    failed = 0

    for server in servers:
        name = server.get("name", "")
        if not server.get("enabled", False):
            continue
        if name in ALWAYS_ON:
            skipped += 1
            continue
        if filter_names and name not in filter_names:
            continue
        if server.get("protocol") != "stdio":
            skipped += 1
            continue

        command = server.get("command", "")
        args = server.get("args", [])
        env = server.get("env")

        tools = await warmup_server(name, command, args, env)

        if tools is not None:
            # Save to mcp/<name>/tools_cache.json
            cache_dir = MCP_DIR / name
            if not cache_dir.exists():
                # Server might be elsewhere (e.g., native binary)
                cache_dir = MCP_DIR
            cache_path = cache_dir / "tools_cache.json"
            cache_path.write_text(json.dumps(tools, indent=2, ensure_ascii=False))
            print(f"  [{name}] Saved {len(tools)} tools -> {cache_path}", flush=True)
            success += 1
        else:
            failed += 1

    print(f"\nDone: {success} cached, {skipped} skipped, {failed} failed")


if __name__ == "__main__":
    asyncio.run(main())
