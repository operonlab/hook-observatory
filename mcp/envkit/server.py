"""Envkit MCP Server -- environment management tools for Claude Code.

4 tools: envkit_snapshot, envkit_verify, envkit_diff, envkit_list.
Destructive operations (bootstrap, backup) are NOT exposed via MCP.

Usage (via .mcp.json):
    uv run --no-project --with 'mcp>=1.0' python3 mcp/envkit/server.py
"""

import asyncio
from asyncio import to_thread

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from workshop.clients.envkit import EnvkitClient, EnvkitError

server = Server("envkit")
client = EnvkitClient()


def text_result(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="envkit_snapshot",
            description=(
                "Take a full macOS environment snapshot -- captures Homebrew formulae/casks, "
                "Python packages, Node.js packages, shell config, Docker, apps, and CLI tools. "
                "Returns YAML output."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "output_file": {
                        "type": "string",
                        "description": "Optional file path to save the snapshot YAML. If omitted, returns content directly.",
                    },
                },
            },
        ),
        Tool(
            name="envkit_verify",
            description=(
                "Verify the current environment against a saved snapshot. "
                "Reports differences: added, removed, or version-changed packages."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "snapshot_path": {
                        "type": "string",
                        "description": "Path to the reference snapshot YAML file to verify against.",
                    },
                },
                "required": ["snapshot_path"],
            },
        ),
        Tool(
            name="envkit_diff",
            description=(
                "Compare two environment snapshots and show differences "
                "(added, removed, version changes across all categories)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_a": {
                        "type": "string",
                        "description": "Path to the first snapshot YAML file.",
                    },
                    "file_b": {
                        "type": "string",
                        "description": "Path to the second snapshot YAML file.",
                    },
                },
                "required": ["file_a", "file_b"],
            },
        ),
        Tool(
            name="envkit_list",
            description=(
                "List installed items by category. "
                "Categories: all, brew, cask, python, node, shell, docker, apps, cli."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "default": "all",
                        "description": "Category to list (default: all).",
                        "enum": [
                            "all",
                            "brew",
                            "cask",
                            "python",
                            "node",
                            "shell",
                            "docker",
                            "apps",
                            "cli",
                        ],
                    },
                },
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        match name:
            case "envkit_snapshot":
                output_file = arguments.get("output_file")
                result = await to_thread(client.snapshot, output_file)
                return text_result(result)

            case "envkit_verify":
                snapshot_path = arguments["snapshot_path"]
                result = await to_thread(client.verify, snapshot_path)
                return text_result(result)

            case "envkit_diff":
                file_a = arguments["file_a"]
                file_b = arguments["file_b"]
                result = await to_thread(client.diff, file_a, file_b)
                return text_result(result)

            case "envkit_list":
                category = arguments.get("category", "all")
                result = await to_thread(client.list_items, category)
                return text_result(result)

            case _:
                return text_result(f"Unknown tool: {name}")

    except EnvkitError as e:
        return text_result(f"Envkit error (rc={e.returncode}): {e}")
    except Exception as e:
        return text_result(f"Error: {type(e).__name__}: {e}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
