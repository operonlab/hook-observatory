"""Envkit MCP Server -- environment management tools for Claude Code.

4 tools: envkit_snapshot, envkit_verify, envkit_diff, envkit_list.
Destructive operations (bootstrap, backup) are NOT exposed via MCP.

Usage (via .mcp.json):
    uv run --no-project --with 'mcp>=1.0' python3 mcp/envkit/server.py
"""

from asyncio import to_thread

from mcp.server.fastmcp import FastMCP
from workshop.clients.envkit import EnvkitClient, EnvkitError

mcp = FastMCP("envkit")
client = EnvkitClient()


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


@mcp.tool()
async def envkit_snapshot(output_file: str = "", summary: bool = True) -> str:
    """Take a full macOS environment snapshot -- captures Homebrew formulae/casks, Python packages, Node.js packages, shell config, Docker, apps, and CLI tools. Returns YAML output. Use summary=true (default) to get category counts + top items only."""
    try:
        result = await to_thread(client.snapshot, output_file or None)
        if summary and not output_file and isinstance(result, str):
            result = _summarize_snapshot(result)
        elif isinstance(result, str) and len(result) > 5000:
            result = result[:5000] + f"\n\n... (truncated, {len(result)} chars total)"
        return result
    except EnvkitError as e:
        return f"Envkit error (rc={e.returncode}): {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def envkit_verify(snapshot_path: str) -> str:
    """Verify the current environment against a saved snapshot. Reports differences: added, removed, or version-changed packages."""
    try:
        result = await to_thread(client.verify, snapshot_path)
        return result
    except EnvkitError as e:
        return f"Envkit error (rc={e.returncode}): {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def envkit_diff(file_a: str, file_b: str) -> str:
    """Compare two environment snapshots and show differences (added, removed, version changes across all categories)."""
    try:
        result = await to_thread(client.diff, file_a, file_b)
        return result
    except EnvkitError as e:
        return f"Envkit error (rc={e.returncode}): {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def envkit_list(category: str = "all", limit: int = 50) -> str:
    """List installed items by category. Categories: all, brew, cask, python, node, shell, docker, apps, cli."""
    try:
        result = await to_thread(client.list_items, category)
        if isinstance(result, str):
            lines = result.splitlines()
            if len(lines) > limit:
                result = (
                    "\n".join(lines[:limit])
                    + f"\n\n... ({len(lines)} lines total, showing {limit})"
                )
        return result
    except EnvkitError as e:
        return f"Envkit error (rc={e.returncode}): {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


if __name__ == "__main__":
    mcp.run()
