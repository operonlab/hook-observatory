#!/usr/bin/env python3
"""MCP Lazy Wrapper — on-demand server lifecycle for mcpproxy.

Sits between mcpproxy and a real MCP server. The wrapper stays alive
(~5MB footprint) while the real server is only spawned on first tool call
and killed after an idle timeout.

Protocol: newline-delimited JSON-RPC 2.0 (MCP stdio transport).

Usage in mcp_config.json:
  {
    "command": "python3",
    "args": [
      "mcp-lazy-wrapper.py",
      "--idle-timeout", "1800",
      "--tools-cache", "tools_cache.json",
      "--name", "my-server",
      "--", "python3", "real_server.py"
    ]
  }
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
import time
from enum import Enum
from pathlib import Path


class State(Enum):
    DORMANT = "dormant"
    STARTING = "starting"
    ACTIVE = "active"


class LazyWrapper:
    def __init__(
        self,
        server_cmd: list[str],
        server_name: str = "unknown",
        idle_timeout: int = 1800,
        tools_cache_path: str | None = None,
        server_env: dict[str, str] | None = None,
    ):
        self.server_cmd = server_cmd
        self.server_name = server_name
        self.idle_timeout = idle_timeout
        self.state = State.DORMANT
        self.proc: asyncio.subprocess.Process | None = None
        self.last_activity = time.monotonic()
        self._id_counter = 0
        self._pending: dict[int | str, asyncio.Future] = {}
        self._startup_event = asyncio.Event()
        self._server_initialized = False
        self._init_params: dict | None = None
        self._tools_cache: list[dict] | None = None
        self._server_env = server_env

        # Load tools cache
        if tools_cache_path:
            cache_path = Path(tools_cache_path).expanduser()
            if cache_path.exists():
                try:
                    self._tools_cache = json.loads(cache_path.read_text())
                    self._log(f"Loaded tools cache: {len(self._tools_cache)} tools")
                except Exception as e:
                    self._log(f"Failed to load tools cache: {e}")

    def _log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        print(f"[lazy:{self.server_name}] [{ts}] {msg}", file=sys.stderr, flush=True)

    def _next_internal_id(self) -> str:
        self._id_counter += 1
        return f"__lazy_internal_{self._id_counter}"

    async def _write_stdout(self, msg: dict):
        """Write a JSON-RPC message to stdout (back to mcpproxy)."""
        line = json.dumps(msg, ensure_ascii=False) + "\n"
        sys.stdout.write(line)
        sys.stdout.flush()

    async def _write_to_server(self, msg: dict):
        """Write a JSON-RPC message to the real server's stdin."""
        if self.proc and self.proc.stdin:
            line = json.dumps(msg, ensure_ascii=False) + "\n"
            self.proc.stdin.write(line.encode("utf-8"))
            await self.proc.stdin.drain()

    async def _spawn_server(self):
        """Spawn the real MCP server subprocess."""
        if self.state != State.DORMANT:
            return

        self.state = State.STARTING
        self._startup_event.clear()
        self._server_initialized = False
        self._log(f"Spawning: {' '.join(self.server_cmd)}")

        env = {**os.environ}
        if self._server_env:
            env.update(self._server_env)

        self.proc = await asyncio.create_subprocess_exec(
            *self.server_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        # Start reading server stdout and stderr
        asyncio.create_task(self._read_server_stdout())
        asyncio.create_task(self._read_server_stderr())

        # Send initialize to real server
        init_id = self._next_internal_id()
        init_request = {
            "jsonrpc": "2.0",
            "id": init_id,
            "method": "initialize",
            "params": self._init_params
            or {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "mcp-lazy-wrapper", "version": "1.0.0"},
            },
        }

        future = asyncio.get_event_loop().create_future()
        self._pending[init_id] = future
        await self._write_to_server(init_request)

        try:
            await asyncio.wait_for(future, timeout=30)
        except TimeoutError:
            self._log("Server initialize timeout (30s)")
            await self._kill_server()
            return

        # Send initialized notification
        await self._write_to_server(
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            }
        )

        self._server_initialized = True
        self.state = State.ACTIVE
        self.last_activity = time.monotonic()
        self._startup_event.set()
        self._log("Server initialized and ACTIVE")

    async def _kill_server(self):
        """Kill the real server subprocess."""
        if self.proc:
            self._log("Killing server (idle timeout)")
            try:
                self.proc.terminate()
                try:
                    await asyncio.wait_for(self.proc.wait(), timeout=5)
                except TimeoutError:
                    self.proc.kill()
                    await self.proc.wait()
            except ProcessLookupError:
                pass
            self.proc = None
        self.state = State.DORMANT
        self._server_initialized = False
        self._startup_event.clear()
        # Clear any pending futures
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()

    async def _read_server_stdout(self):
        """Read JSON-RPC messages from the real server's stdout."""
        if not self.proc or not self.proc.stdout:
            return
        try:
            while True:
                line = await self.proc.stdout.readline()
                if not line:
                    break
                line = line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    self._log(f"Bad JSON from server: {line[:100]}")
                    continue

                msg_id = msg.get("id")

                # Check if this is a response to an internal request
                if msg_id and msg_id in self._pending:
                    future = self._pending.pop(msg_id)
                    if not future.done():
                        future.set_result(msg)
                    continue

                # Forward to mcpproxy (response or notification from real server)
                await self._write_stdout(msg)
        except Exception as e:
            self._log(f"Server stdout reader error: {e}")
        finally:
            # Server exited
            if self.state == State.ACTIVE:
                self._log("Server process exited unexpectedly")
                self.state = State.DORMANT
                self._server_initialized = False

    async def _read_server_stderr(self):
        """Relay real server stderr with prefix."""
        if not self.proc or not self.proc.stderr:
            return
        try:
            while True:
                line = await self.proc.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    print(f"[{self.server_name}] {text}", file=sys.stderr, flush=True)
        except Exception:
            pass

    async def _idle_monitor(self):
        """Periodically check for idle timeout and kill server."""
        while True:
            await asyncio.sleep(60)  # Check every minute
            if self.state == State.ACTIVE:
                elapsed = time.monotonic() - self.last_activity
                if elapsed > self.idle_timeout:
                    self._log(f"Idle timeout ({int(elapsed)}s > {self.idle_timeout}s)")
                    await self._kill_server()

    def _make_tools_list_response(self, msg_id) -> dict:
        """Build a tools/list response from cache."""
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"tools": self._tools_cache or []},
        }

    async def _handle_message(self, msg: dict):
        """Route incoming JSON-RPC message from mcpproxy."""
        method = msg.get("method")
        msg_id = msg.get("id")  # None for notifications

        # ── initialize ──
        if method == "initialize":
            self._init_params = msg.get("params", {})
            # Respond directly (we handle initialization internally)
            response = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {
                        "name": f"lazy-{self.server_name}",
                        "version": "1.0.0",
                    },
                },
            }
            await self._write_stdout(response)
            return

        # ── notifications/initialized ──
        if method == "notifications/initialized":
            return  # Acknowledge silently

        # ── ping ──
        if method == "ping":
            await self._write_stdout({"jsonrpc": "2.0", "id": msg_id, "result": {}})
            return

        # ── tools/list ──
        if method == "tools/list":
            if self.state == State.ACTIVE:
                # Forward to real server and update cache
                future = asyncio.get_event_loop().create_future()
                self._pending[msg_id] = future
                await self._write_to_server(msg)
                try:
                    response = await asyncio.wait_for(future, timeout=10)
                    # Update cache
                    tools = response.get("result", {}).get("tools", [])
                    if tools:
                        self._tools_cache = tools
                    await self._write_stdout(response)
                except TimeoutError:
                    # Fall back to cache
                    await self._write_stdout(self._make_tools_list_response(msg_id))
            else:
                # DORMANT: respond from cache (don't spawn for polling)
                await self._write_stdout(self._make_tools_list_response(msg_id))
            return

        # ── tools/call (triggers spawn) ──
        if method == "tools/call":
            self.last_activity = time.monotonic()

            if self.state == State.DORMANT:
                self._log(
                    f"tools/call triggered spawn for: {msg.get('params', {}).get('name', '?')}"
                )
                await self._spawn_server()

            if self.state == State.STARTING:
                # Wait for startup to complete
                try:
                    await asyncio.wait_for(self._startup_event.wait(), timeout=30)
                except TimeoutError:
                    await self._write_stdout(
                        {
                            "jsonrpc": "2.0",
                            "id": msg_id,
                            "error": {
                                "code": -32603,
                                "message": f"Server {self.server_name} failed to start",
                            },
                        }
                    )
                    return

            if self.state != State.ACTIVE:
                await self._write_stdout(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {
                            "code": -32603,
                            "message": f"Server {self.server_name} is not available",
                        },
                    }
                )
                return

            # Forward to real server
            future = asyncio.get_event_loop().create_future()
            self._pending[msg_id] = future
            await self._write_to_server(msg)
            try:
                response = await asyncio.wait_for(future, timeout=120)
                await self._write_stdout(response)
            except TimeoutError:
                self._pending.pop(msg_id, None)
                await self._write_stdout(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {
                            "code": -32603,
                            "message": f"Server {self.server_name} tool call timeout (120s)",
                        },
                    }
                )
            return

        # ── resources/*, prompts/*, completion/* — forward if active ──
        if msg_id is not None and self.state == State.ACTIVE:
            self.last_activity = time.monotonic()
            future = asyncio.get_event_loop().create_future()
            self._pending[msg_id] = future
            await self._write_to_server(msg)
            try:
                response = await asyncio.wait_for(future, timeout=30)
                await self._write_stdout(response)
            except TimeoutError:
                self._pending.pop(msg_id, None)
                await self._write_stdout(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {"code": -32603, "message": "Request timeout"},
                    }
                )
            return

        # Unknown method with id — return method not found
        if msg_id is not None:
            await self._write_stdout(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}",
                    },
                }
            )

    async def run(self):
        """Main event loop."""
        self._log(
            f"Started (idle_timeout={self.idle_timeout}s, "
            f"cache={'yes' if self._tools_cache else 'no'})"
        )

        # Start idle monitor
        asyncio.create_task(self._idle_monitor())

        # Read from stdin (mcpproxy)
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin.buffer)

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    msg = json.loads(text)
                except json.JSONDecodeError:
                    self._log(f"Bad JSON from mcpproxy: {text[:100]}")
                    continue
                await self._handle_message(msg)
        except Exception as e:
            self._log(f"Main loop error: {e}")
        finally:
            await self._kill_server()
            self._log("Wrapper exiting")


def main():
    parser = argparse.ArgumentParser(description="MCP Lazy Wrapper")
    parser.add_argument("--name", default="unknown", help="Server name for logging")
    parser.add_argument(
        "--idle-timeout", type=int, default=1800, help="Idle timeout in seconds (default: 1800)"
    )
    parser.add_argument("--tools-cache", default=None, help="Path to tools_cache.json")
    parser.add_argument(
        "server_cmd", nargs=argparse.REMAINDER, help="Real server command (after --)"
    )

    args = parser.parse_args()

    # Strip leading -- from server_cmd
    cmd = args.server_cmd
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]

    if not cmd:
        print("Error: no server command specified", file=sys.stderr)
        sys.exit(1)

    wrapper = LazyWrapper(
        server_cmd=cmd,
        server_name=args.name,
        idle_timeout=args.idle_timeout,
        tools_cache_path=args.tools_cache,
    )

    # Handle SIGTERM/SIGINT gracefully
    def shutdown(signum, frame):
        wrapper._log(f"Received signal {signum}, shutting down")
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    asyncio.run(wrapper.run())


if __name__ == "__main__":
    main()
