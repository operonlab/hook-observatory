#!/usr/bin/env python3
"""tmux-relay MCP Server — event-driven async dispatch.

Primary tool: relay_run — synchronous-blocking relay that awaits completion
via relay.sh's tmux wait-for mechanism (zero-CPU, event-driven).
Designed to be called from Claude Code's background agents for true async.

Low-level tools (relay_dispatch/check/result) retained for manual control.

Usage (via .mcp.json):
    uv run --no-project --with 'mcp>=1.0' python3 mcp/tmux-relay/server.py
"""

import asyncio
import os
import time
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

SCRIPTS_DIR = Path.home() / ".claude/skills/tmux-relay/scripts"
PANE_POOL = SCRIPTS_DIR / "pane_pool.sh"
RELAY_SH = SCRIPTS_DIR / "relay.sh"

server = Server("tmux-relay")


# ======================== Helpers ========================


async def run_script(script: Path, *args: str, timeout: float = 30) -> str:
    """Run a shell script and return stdout."""
    proc = await asyncio.create_subprocess_exec(
        "bash",
        str(script),
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        raise RuntimeError(f"Script timed out after {timeout}s: {script.name} {' '.join(args)}")
    if proc.returncode != 0:
        err = stderr.decode().strip()
        raise RuntimeError(f"{script.name} failed (rc={proc.returncode}): {err}")
    return stdout.decode().strip()


def text_result(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


# ======================== Tool Definitions ========================


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="relay_run",
            description=(
                "Blocking relay: acquire pane → send command → wait for completion "
                "(event-driven via tmux wait-for, zero CPU) → return result. "
                "Use from a background Agent for true async. This is the PRIMARY tool."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The command/prompt to send to the relay pane",
                    },
                    "timeout": {
                        "type": "integer",
                        "default": 600,
                        "description": "Max seconds to wait for completion",
                    },
                    "lines": {
                        "type": "integer",
                        "default": 200,
                        "description": "Max lines of output to return",
                    },
                },
                "required": ["command"],
            },
        ),
        Tool(
            name="relay_dispatch",
            description=(
                "Low-level: fire-and-forget dispatch. Returns signal_file for manual "
                "polling via relay_check/relay_result. Prefer relay_run instead."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The command/prompt to send to the relay pane",
                    },
                    "timeout": {
                        "type": "integer",
                        "default": 600,
                        "description": "Max seconds to wait for completion (background)",
                    },
                    "count": {
                        "type": "integer",
                        "default": 1,
                        "description": "Number of panes to dispatch to (for parallel tasks)",
                    },
                },
                "required": ["command"],
            },
        ),
        Tool(
            name="relay_list",
            description="List all relay panes with their idle/busy status.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="relay_check",
            description="Low-level: check if a dispatched command has completed (poll signal file).",
            inputSchema={
                "type": "object",
                "properties": {
                    "signal_file": {
                        "type": "string",
                        "description": "Path to the .done signal file returned by relay_dispatch",
                    },
                },
                "required": ["signal_file"],
            },
        ),
        Tool(
            name="relay_result",
            description="Low-level: read the output of a completed relay command.",
            inputSchema={
                "type": "object",
                "properties": {
                    "signal_file": {
                        "type": "string",
                        "description": "Path to the .done signal file",
                    },
                    "lines": {
                        "type": "integer",
                        "default": 200,
                        "description": "Max lines of output to return",
                    },
                },
                "required": ["signal_file"],
            },
        ),
    ]


# ======================== Tool Handlers ========================


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        match name:
            case "relay_run":
                return await handle_run(arguments)
            case "relay_dispatch":
                return await handle_dispatch(arguments)
            case "relay_list":
                return await handle_list(arguments)
            case "relay_check":
                return await handle_check(arguments)
            case "relay_result":
                return await handle_result(arguments)
            case _:
                return text_result(f"Unknown tool: {name}")
    except RuntimeError as e:
        return text_result(f"Error: {e}")
    except Exception as e:
        return text_result(f"Unexpected error: {type(e).__name__}: {e}")


# ======================== Tool Implementations ========================


async def handle_run(args: dict) -> list[TextContent]:
    """Blocking relay: acquire → recycle if busy → dispatch → AWAIT completion → return result."""
    command = args["command"]
    timeout = args.get("timeout", 600)
    max_lines = args.get("lines", 200)

    # 1. Acquire a single pane
    raw = await run_script(PANE_POOL, "acquire", "1", timeout=30)
    pane = raw.strip().splitlines()[0].strip() if raw.strip() else ""
    if not pane:
        return text_result("Failed to acquire relay pane. Is tmux running?")

    # 2. Recycle if busy
    try:
        status = await run_script(PANE_POOL, "status", pane, timeout=10)
    except RuntimeError:
        status = "unknown"

    if status.startswith("busy"):
        try:
            await run_script(PANE_POOL, "recycle", pane, timeout=30)
            for _ in range(10):
                await asyncio.sleep(1.5)
                try:
                    status = await run_script(PANE_POOL, "status", pane, timeout=10)
                except RuntimeError:
                    status = "unknown"
                if status == "idle":
                    break
        except RuntimeError as e:
            return text_result(f"Pane {pane}: recycle failed — {e}")

    # 3. Run relay.sh and AWAIT it (blocks until tmux wait-for signals)
    signal_file = f"/tmp/relay-mcp-{int(time.time() * 1000)}-{os.getpid()}.done"
    try:
        await run_script(
            RELAY_SH,
            pane,  # source pane
            "",  # target pane (empty = no forward)
            command,  # the command to send
            "--no-forward",
            "--signal",
            signal_file,
            "--timeout",
            str(timeout),
            timeout=timeout + 10,  # script timeout slightly longer than relay timeout
        )
    except RuntimeError as e:
        return text_result(f"Relay failed on {pane}: {e}")

    # 4. Read signal file metadata
    meta = ""
    if os.path.exists(signal_file):
        try:
            meta = Path(signal_file).read_text().strip()
        except OSError:
            meta = "(signal unreadable)"

    # 5. Read result file
    result_file = signal_file.replace(".done", ".txt")
    if not os.path.exists(result_file):
        return text_result(f"Relay completed but no result file.\nPane: {pane}\n{meta}")

    try:
        lines = Path(result_file).read_text().splitlines()
        total = len(lines)
        truncated = lines[:max_lines]
        output = "\n".join(truncated)
        if total > max_lines:
            output += f"\n\n... ({total - max_lines} more lines truncated)"
        return text_result(
            f"# Relay Result\n\nPane: {pane}\n{meta}\n\n## Output ({total} lines)\n\n{output}"
        )
    except OSError as e:
        return text_result(f"Error reading result: {e}")


async def handle_dispatch(args: dict) -> list[TextContent]:
    """Acquire pane(s) → recycle if busy → dispatch command (background)."""
    command = args["command"]
    timeout = args.get("timeout", 600)
    count = args.get("count", 1)

    # 1. Acquire panes
    raw = await run_script(PANE_POOL, "acquire", str(count), timeout=30)
    panes = [p.strip() for p in raw.splitlines() if p.strip()]
    if not panes:
        return text_result("Failed to acquire relay panes. Is tmux running?")

    results = []
    for pane in panes:
        # 2. Check status → recycle if busy
        try:
            status = await run_script(PANE_POOL, "status", pane, timeout=10)
        except RuntimeError:
            status = "unknown"

        if status.startswith("busy"):
            try:
                await run_script(PANE_POOL, "recycle", pane, timeout=30)
                # Wait for recycle to complete
                for _ in range(10):
                    await asyncio.sleep(1.5)
                    try:
                        status = await run_script(PANE_POOL, "status", pane, timeout=10)
                    except RuntimeError:
                        status = "unknown"
                    if status == "idle":
                        break
            except RuntimeError as e:
                results.append(f"Pane {pane}: recycle failed — {e}")
                continue

        # 3. Dispatch (background — relay.sh runs async)
        signal_file = f"/tmp/relay-mcp-{int(time.time() * 1000)}-{os.getpid()}.done"
        proc = await asyncio.create_subprocess_exec(
            "bash",
            str(RELAY_SH),
            pane,  # source pane
            "",  # target pane (empty = no forward)
            command,  # the command to send
            "--no-forward",
            "--signal",
            signal_file,
            "--timeout",
            str(timeout),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        # Detach — don't await. The process runs in background.
        results.append(f"Pane: {pane}\nSignal: {signal_file}\nPID: {proc.pid}")

    header = f"Dispatched {len(results)} task(s)\n\n"
    return text_result(header + "\n---\n".join(results))


async def handle_list(args: dict) -> list[TextContent]:
    """List relay panes with status."""
    raw = await run_script(PANE_POOL, "list", timeout=10)
    if not raw:
        return text_result("No relay panes found.")
    return text_result(f"# Relay Panes\n\n{raw}")


async def handle_check(args: dict) -> list[TextContent]:
    """Check if a signal file exists (command completed)."""
    signal_file = args["signal_file"]
    if os.path.exists(signal_file):
        # Read signal file content for status
        try:
            content = Path(signal_file).read_text().strip()
        except OSError:
            content = "(unreadable)"
        return text_result(f"Status: COMPLETED\nSignal: {signal_file}\n{content}")
    else:
        return text_result(f"Status: RUNNING\nSignal: {signal_file}")


async def handle_result(args: dict) -> list[TextContent]:
    """Read the result file (.txt) associated with a signal file."""
    signal_file = args["signal_file"]
    max_lines = args.get("lines", 200)

    # Result file is signal_file with .done → .txt
    result_file = signal_file.replace(".done", ".txt")

    if not os.path.exists(signal_file):
        return text_result(f"Task not yet completed.\nSignal: {signal_file}")

    if not os.path.exists(result_file):
        return text_result(
            f"Task completed but no result file found.\n"
            f"Signal: {signal_file}\nExpected: {result_file}"
        )

    try:
        lines = Path(result_file).read_text().splitlines()
        total = len(lines)
        truncated = lines[:max_lines]
        output = "\n".join(truncated)
        if total > max_lines:
            output += f"\n\n... ({total - max_lines} more lines truncated)"
        return text_result(f"# Result ({total} lines)\n\n{output}")
    except OSError as e:
        return text_result(f"Error reading result: {e}")


# ======================== Main ========================


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
