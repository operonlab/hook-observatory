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
                "Returns YAML output. Use summary=true (default) to get category counts + top items only."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "output_file": {
                        "type": "string",
                        "description": "Optional file path to save the snapshot YAML. If omitted, returns content directly.",
                    },
                    "summary": {
                        "type": "boolean",
                        "default": True,
                        "description": "If true, return summary (counts + top items per category) instead of full YAML.",
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
                    "limit": {
                        "type": "integer",
                        "default": 50,
                        "description": "Maximum number of items to return per category.",
                    },
                },
            },
        ),
    ]


def _summarize_snapshot(yaml_text: str) -> str:
    """Summarize a full snapshot YAML into category counts + top items."""
    lines = yaml_text.splitlines()
    summary_lines: list[str] = ["# Environment Snapshot (Summary)\n"]
    current_section = ""
    section_items: list[str] = []

    def flush_section():
        if current_section and section_items:
            summary_lines.append(f"## {current_section} ({len(section_items)} items)")
            for item in section_items[:5]:
                summary_lines.append(f"  - {item.strip().lstrip('- ')}")
            if len(section_items) > 5:
                summary_lines.append(f"  ... and {len(section_items) - 5} more")
            summary_lines.append("")

    for line in lines:
        stripped = line.rstrip()
        if stripped and not stripped.startswith(" ") and stripped.endswith(":"):
            flush_section()
            current_section = stripped.rstrip(":")
            section_items = []
        elif stripped.startswith("  - ") or stripped.startswith("  "):
            section_items.append(stripped)

    flush_section()
    return "\n".join(summary_lines)


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        match name:
            case "envkit_snapshot":
                output_file = arguments.get("output_file")
                result = await to_thread(client.snapshot, output_file)
                summary = arguments.get("summary", True)
                if summary and not output_file and isinstance(result, str):
                    result = _summarize_snapshot(result)
                elif isinstance(result, str) and len(result) > 5000:
                    result = result[:5000] + f"\n\n... (truncated, {len(result)} chars total)"
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
                limit = arguments.get("limit", 50)
                if isinstance(result, str):
                    lines = result.splitlines()
                    if len(lines) > limit:
                        result = (
                            "\n".join(lines[:limit])
                            + f"\n\n... ({len(lines)} lines total, showing {limit})"
                        )
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
