#!/usr/bin/env python3
"""Remote Node MCP Server — Thin wrapper over RemoteNodeClient SDK.

Configure in mcpproxy:
    "remote-node": {
        "command": "/Users/joneshong/.local/bin/python3",
        "args": ["/Users/joneshong/workshop/mcp/remote-node/server.py"]
    }
"""

import json
from asyncio import to_thread

from mcp.server.fastmcp import FastMCP
from workshop.clients.remote_node import RemoteNodeClient
from workshop.mcp_helpers import json_text, mcp_error_handler

mcp = FastMCP("remote-node")
client = RemoteNodeClient()


@mcp.tool()
@mcp_error_handler("Remote Node")
async def remote_node_status() -> str:
    """Check remote GPU node status: connectivity, VRAM usage, loaded models."""
    result = await to_thread(client.health)

    # Proxy returns flat fields: remote_healthy, remote_url, remote_last_error
    connected = result.get("remote_healthy", False)

    parts = [
        f"**Proxy**: {result.get('status', 'unknown')} (port {result.get('port', '?')})",
        f"**Remote URL**: {result.get('remote_url', '?')}",
        f"**Windows GPU**: {'connected' if connected else 'disconnected'}",
    ]
    if result.get("remote_last_error"):
        parts.append(f"**Last error**: {result['remote_last_error']}")

    # If connected, try to fetch model info
    if connected:
        try:
            models = await to_thread(client.list_models)
            loaded = models.get("loaded", [])
            available = models.get("available", [])
            if loaded:
                parts.append(f"**Models loaded**: {', '.join(loaded)}")
            if available:
                parts.append(f"**Available**: {', '.join(available)}")
            if models.get("vram"):
                vram = models["vram"]
                parts.append(f"**VRAM**: {vram.get('used', '?')} / {vram.get('total', '?')}")
        except Exception:
            pass  # Non-critical

    return "\n".join(parts)


@mcp.tool()
@mcp_error_handler("Remote Node")
async def remote_node_segment(file_path: str, prompt: str) -> str:
    """Segment an image region matching a text prompt (Florence-2).

    Examples: 'silver hair', 'fairy wings', 'open book', 'dark dress'
    Returns a mask PNG and polygon coordinates.
    """
    result = await to_thread(client.segment, file_path=file_path, prompt=prompt)

    mask_path = result.get("mask_path", "")
    polygons = result.get("polygons", [])
    n_regions = len(polygons) if isinstance(polygons, list) else 0

    parts = [
        f"**Prompt**: {prompt}",
        f"**Mask saved**: {mask_path}",
        f"**Regions found**: {n_regions}",
    ]
    return "\n".join(parts)


@mcp.tool()
@mcp_error_handler("Remote Node")
async def remote_node_detect(file_path: str, prompt: str) -> str:
    """Detect objects matching a text prompt in an image (Florence-2).

    Returns bounding boxes with labels and confidence scores.
    """
    result = await to_thread(client.detect, file_path=file_path, prompt=prompt)

    boxes = result.get("boxes", [])
    labels = result.get("labels", [])
    scores = result.get("scores", [])

    parts = [f"**Detected {len(boxes)} objects**:"]
    for i, (box, label, score) in enumerate(zip(boxes, labels, scores)):
        parts.append(f"  {i+1}. {label} (score={score:.2f}) box={box}")

    return "\n".join(parts)


@mcp.tool()
@mcp_error_handler("Remote Node")
async def remote_node_caption(
    file_path: str, detail: str = "brief"
) -> str:
    """Generate a text caption for an image (Florence-2).

    detail: 'brief' for short caption, 'detailed' for long description.
    """
    result = await to_thread(client.caption, file_path=file_path, detail=detail)
    caption = result.get("caption", "")
    return f"**Caption** ({detail}): {caption}"


@mcp.tool()
@mcp_error_handler("Remote Node")
async def remote_node_batch_segment(
    file_path: str, prompts: str
) -> str:
    """Segment multiple parts of an image at once.

    prompts: comma-separated list, e.g. 'silver hair, eyes, fairy wings, open book'
    """
    prompt_list = [p.strip() for p in prompts.split(",") if p.strip()]
    result = await to_thread(
        client.batch_segment, file_path=file_path, prompts=prompt_list
    )

    parts = [f"**Batch segment**: {len(prompt_list)} prompts"]
    results_dict = result.get("results", {})
    for prompt_name, data in results_dict.items():
        mask_path = data.get("mask_path", "?")
        parts.append(f"  - **{prompt_name}**: {mask_path}")

    composite = result.get("composite_mask_path", "")
    if composite:
        parts.append(f"**Composite mask**: {composite}")

    return "\n".join(parts)


@mcp.tool()
@mcp_error_handler("Remote Node")
async def remote_node_models() -> str:
    """List available and loaded GPU models on the remote node."""
    result = await to_thread(client.list_models)
    return json_text(result)


if __name__ == "__main__":
    mcp.run()
