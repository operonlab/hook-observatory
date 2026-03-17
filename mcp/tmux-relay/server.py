#!/usr/bin/env python3
"""tmux-relay MCP Server — Thin wrapper over TmuxRelayClient SDK.

5 tools: relay_run, relay_dispatch, relay_list, relay_check, relay_result.
All logic lives in workshop.clients.tmux_relay (SDK layer).

Usage:
    python3 mcp/tmux-relay/server.py

Configure in ~/.claude.json:
    "tmux-relay": {
        "command": "/Users/joneshong/.local/bin/python3",
        "args": ["/Users/joneshong/workshop/mcp/tmux-relay/server.py"],
        "env": {}
    }
"""

from asyncio import to_thread

from mcp.server.fastmcp import FastMCP
from workshop.clients.tmux_relay import TmuxRelayClient, TmuxRelayError

mcp = FastMCP("tmux-relay")
_default_client = TmuxRelayClient(silent=True)


def _client(model: str | None = None, silent: bool = True) -> TmuxRelayClient:
    """Return a client with optional model/silent override."""
    if model or not silent:
        return TmuxRelayClient(model=model, silent=silent)
    return _default_client


# ======================== Result Formatting ========================


def _format_relay_result(result) -> str:
    parts = [f"**Pane**: {result.pane}"]
    if result.status:
        parts.append(f"**Status**: {result.status}")
    if result.elapsed:
        parts.append(f"**Elapsed**: {result.elapsed}")
    if result.result_file:
        parts.append(f"**Result file**: {result.result_file}")
    if result.output:
        total_lines = result.output.count("\n") + 1
        parts.append(f"\n## Output ({total_lines} lines)\n\n{result.output}")
    return "\n".join(parts)


def _format_dispatch(dispatched: list[dict]) -> str:
    parts = [f"**Dispatched {len(dispatched)} task(s)**\n"]
    for d in dispatched:
        parts.append(f"- Pane: {d['pane']}, Signal: {d['signal_file']}, PID: {d['pid']}")
    return "\n".join(parts)


def _format_panes(panes) -> str:
    if not panes:
        return "No relay panes found."
    parts = ["### Relay Panes\n"]
    for p in panes:
        indicator = "🟢" if p.status == "idle" else "🔴"
        parts.append(f"- {indicator} **{p.pane_ref}** — {p.status} ({p.pane_id})")
    return "\n".join(parts)


# ======================== Tools ========================


@mcp.tool()
async def relay_run(
    command: str,
    timeout: int = 600,
    lines: int = 200,
    model: str | None = None,
    silent: bool = True,
) -> str:
    """Blocking relay: acquire pane → send command → wait for completion (event-driven via tmux wait-for, zero CPU) → return result. Use from a background Agent for true async. This is the PRIMARY tool."""
    try:
        c = _client(model, silent)
        result = await to_thread(
            c.run,
            command=command,
            timeout=timeout,
            max_lines=lines,
        )
        return _format_relay_result(result)
    except TmuxRelayError as e:
        return f"tmux-relay error: {e}"
    except Exception as e:
        return f"Unexpected error: {type(e).__name__}: {e}"


@mcp.tool()
async def relay_dispatch(
    command: str,
    timeout: int = 600,
    count: int = 1,
    model: str | None = None,
    silent: bool = True,
) -> str:
    """Low-level: fire-and-forget dispatch. Returns signal_file for manual polling via relay_check/relay_result. Prefer relay_run instead."""
    try:
        c = _client(model, silent)
        dispatched = await to_thread(
            c.dispatch,
            command=command,
            timeout=timeout,
            count=count,
        )
        return _format_dispatch(dispatched)
    except TmuxRelayError as e:
        return f"tmux-relay error: {e}"
    except Exception as e:
        return f"Unexpected error: {type(e).__name__}: {e}"


@mcp.tool()
async def relay_list() -> str:
    """List all relay panes with their idle/busy status (cache-backed, ~0.5ms)."""
    try:
        panes = await to_thread(_default_client.list_panes)
        return _format_panes(panes)
    except TmuxRelayError as e:
        return f"tmux-relay error: {e}"
    except Exception as e:
        return f"Unexpected error: {type(e).__name__}: {e}"


@mcp.tool()
async def relay_check(signal_file: str) -> str:
    """Low-level: check if a dispatched command has completed (cache-backed, ~0.1ms)."""
    try:
        result = await to_thread(
            _default_client.check,
            signal_file=signal_file,
        )
        status = result.get("status", "unknown").upper()
        meta = result.get("meta", "")
        return f"**Status**: {status}\nSignal: {result.get('signal_file', '')}\n{meta}"
    except TmuxRelayError as e:
        return f"tmux-relay error: {e}"
    except Exception as e:
        return f"Unexpected error: {type(e).__name__}: {e}"


@mcp.tool()
async def relay_result(signal_file: str, lines: int = 200) -> str:
    """Low-level: read the output of a completed relay command."""
    try:
        result = await to_thread(
            _default_client.result,
            signal_file=signal_file,
            max_lines=lines,
        )
        return _format_relay_result(result)
    except TmuxRelayError as e:
        return f"tmux-relay error: {e}"
    except Exception as e:
        return f"Unexpected error: {type(e).__name__}: {e}"


if __name__ == "__main__":
    mcp.run()
