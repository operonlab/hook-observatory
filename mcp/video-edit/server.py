#!/usr/bin/env python3
"""video-edit MCP Server — Thin wrapper over VideoEditClient SDK.

14 tools: project create/list/open/save/info, clip add/cut/trim/remove,
          subtitle, transition, filter, audio, preview, render.

All logic lives in workshop.clients.video_edit (SDK layer).

Usage:
    python3 mcp/video-edit/server.py

Configure in mcpproxy:
    "video-edit": {
        "command": "/Users/joneshong/.local/bin/python3",
        "args": ["/Users/joneshong/workshop/mcp/video-edit/server.py"]
    }
"""

from asyncio import to_thread

from mcp.server.fastmcp import FastMCP
from sdk_client.video_edit import VideoEditClient
from sdk_client.mcp_helpers import json_text, mcp_error_handler

mcp = FastMCP("video-edit")
client = VideoEditClient(render_timeout=600)


# ======================== Projects ========================


@mcp.tool()
@mcp_error_handler("VideoEdit")
async def vedit_create_project(
    name: str,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
    num_tracks: int = 3,
) -> str:
    """Create a new video editing project. Returns project ID and path."""
    result = await to_thread(
        client.create_project, name, width=width, height=height, fps_num=fps, num_tracks=num_tracks
    )
    return (
        f"Project created: **{result['name']}**\n"
        f"- ID: `{result['id']}`\n"
        f"- Path: `{result['path']}`\n"
        f"- Resolution: {result.get('width', width)}x{result.get('height', height)} @ {fps}fps\n"
        f"- Tracks: {num_tracks}"
    )


@mcp.tool()
@mcp_error_handler("VideoEdit")
async def vedit_list_projects() -> str:
    """List all video editing projects."""
    projects = await to_thread(client.list_projects)
    if not projects:
        return "No projects found."
    lines = ["**Projects:**"]
    for p in projects:
        lines.append(f"- {p['name']} → `{p['path']}`")
    return "\n".join(lines)


@mcp.tool()
@mcp_error_handler("VideoEdit")
async def vedit_open_project(path: str) -> str:
    """Open an existing .mlt project file. Returns project ID for subsequent operations."""
    result = await to_thread(client.open_project, path)
    return (
        f"Opened: **{result['name']}**\n"
        f"- ID: `{result['id']}`\n"
        f"- Resolution: {result.get('width')}x{result.get('height')}\n"
        f"- Tracks: {result.get('tracks')}, Clips: {result.get('clips', 0)}"
    )


@mcp.tool()
@mcp_error_handler("VideoEdit")
async def vedit_save(project_id: str) -> str:
    """Save the current project state to disk."""
    result = await to_thread(client.save_project, project_id)
    return f"Saved to: `{result['path']}`"


@mcp.tool()
@mcp_error_handler("VideoEdit")
async def vedit_timeline_info(project_id: str) -> str:
    """Get timeline summary: tracks, clips, transitions. Use this to understand current project state."""
    result = await to_thread(client.timeline_info, project_id)
    return json_text(result)


# ======================== Clips ========================


@mcp.tool()
@mcp_error_handler("VideoEdit")
async def vedit_add_clip(
    project_id: str,
    file_path: str,
    track: int = 0,
    in_point: float = 0,
    out_point: float = 0,
) -> str:
    """Add a media file (video/audio/image) to the timeline at the specified track.
    Set out_point=0 to use the full media duration."""
    result = await to_thread(
        client.add_clip,
        project_id,
        file_path,
        track=track,
        in_point=in_point,
        out_point=out_point if out_point > 0 else None,
    )
    return (
        f"Added clip `{result['clip_id']}`\n"
        f"- File: {result['resource']}\n"
        f"- Track: {result['track']}\n"
        f"- Range: {result['in']} → {result['out']}"
    )


@mcp.tool()
@mcp_error_handler("VideoEdit")
async def vedit_cut_clip(project_id: str, clip_id: str, at_time: float) -> str:
    """Cut a clip at the specified time (seconds), splitting it into two segments."""
    result = await to_thread(client.cut_clip, project_id, clip_id, at_time)
    return (
        f"Cut at {result['cut_at']}\n"
        f"- Part 1: {result['part1']['in']} → {result['part1']['out']}\n"
        f"- Part 2: {result['part2']['in']} → {result['part2']['out']}"
    )


@mcp.tool()
@mcp_error_handler("VideoEdit")
async def vedit_trim_clip(
    project_id: str,
    clip_id: str,
    in_point: float = -1,
    out_point: float = -1,
) -> str:
    """Adjust a clip's in/out points (seconds). Use -1 to keep current value."""
    result = await to_thread(
        client.trim_clip,
        project_id,
        clip_id,
        in_point=in_point if in_point >= 0 else None,
        out_point=out_point if out_point >= 0 else None,
    )
    return f"Trimmed `{result['clip_id']}`: {result['in']} → {result['out']}"


@mcp.tool()
@mcp_error_handler("VideoEdit")
async def vedit_remove_clip(project_id: str, clip_id: str) -> str:
    """Remove a clip from the timeline."""
    await to_thread(client.remove_clip, project_id, clip_id)
    return f"Removed clip `{clip_id}`"


# ======================== Effects ========================


@mcp.tool()
@mcp_error_handler("VideoEdit")
async def vedit_add_subtitle(
    project_id: str,
    text: str,
    start: float,
    end: float,
    font_size: int = 48,
) -> str:
    """Add a text subtitle overlay at the specified time range."""
    result = await to_thread(
        client.add_subtitle, project_id, text, start=start, end=end, font_size=font_size
    )
    return (
        f"Added subtitle `{result['subtitle_id']}`\n"
        f'- "{text}"\n'
        f"- Range: {result['start']} → {result['end']}"
    )


@mcp.tool()
@mcp_error_handler("VideoEdit")
async def vedit_add_transition(
    project_id: str,
    a_track: int,
    b_track: int,
    transition_type: str = "luma",
    in_time: float = 0,
    out_time: float = 2,
) -> str:
    """Add a transition effect between two tracks. Types: luma, dissolve, composite."""
    result = await to_thread(
        client.add_transition,
        project_id,
        a_track=a_track,
        b_track=b_track,
        transition_type=transition_type,
        in_time=in_time,
        out_time=out_time,
    )
    return (
        f"Added {result['type']} transition `{result['transition_id']}`\n"
        f"- Tracks: {result['a_track']} → {result['b_track']}\n"
        f"- Range: {result['in']} → {result['out']}"
    )


@mcp.tool()
@mcp_error_handler("VideoEdit")
async def vedit_add_filter(
    project_id: str,
    clip_id: str,
    filter_type: str,
    params: str = "",
) -> str:
    """Add a filter/effect to a clip. Common filters: brightness, volume, charcoal, greyscale.
    params: comma-separated key=value pairs (e.g., 'level=1.2,saturation=0.5')."""
    parsed_params = {}
    if params:
        for pair in params.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                parsed_params[k.strip()] = v.strip()
    result = await to_thread(
        client.add_filter, project_id, clip_id, filter_type, parsed_params or None
    )
    return f"Added filter `{result['filter_id']}` ({result['type']}) to clip `{clip_id}`"


@mcp.tool()
@mcp_error_handler("VideoEdit")
async def vedit_adjust_audio(
    project_id: str,
    clip_id: str,
    volume: float = -1,
    fade_in: float = -1,
    fade_out: float = -1,
) -> str:
    """Adjust audio: volume (1.0=normal), fade_in/fade_out (seconds). Use -1 to skip."""
    result = await to_thread(
        client.adjust_audio,
        project_id,
        clip_id,
        volume=volume if volume >= 0 else None,
        fade_in=fade_in if fade_in >= 0 else None,
        fade_out=fade_out if fade_out >= 0 else None,
    )
    parts = [f"Audio adjusted for `{clip_id}`"]
    if "volume" in result:
        parts.append(f"- Volume: {result['volume']}")
    if "fade_in" in result:
        parts.append(f"- Fade in: {result['fade_in']}s")
    if "fade_out" in result:
        parts.append(f"- Fade out: {result['fade_out']}s")
    return "\n".join(parts)


@mcp.tool()
@mcp_error_handler("VideoEdit")
async def vedit_add_image_overlay(
    project_id: str,
    file_path: str,
    start: float,
    duration: float,
    track: int = 1,
    geometry: str = "0/0:100%x100%",
    fade_in: float = 0.5,
    fade_out: float = 0.5,
    opacity: float = 1.0,
) -> str:
    """Overlay an image (PNG/JPG) on the timeline at a specific time with fade in/out."""
    result = await to_thread(
        client.add_image_overlay,
        project_id,
        file_path,
        start=start,
        duration=duration,
        track=track,
        geometry=geometry,
        fade_in=fade_in,
        fade_out=fade_out,
        opacity=opacity,
    )
    return (
        f"Added overlay `{result['overlay_id']}`\n"
        f"- File: {result['file']}\n"
        f"- Start: {result['start']}s, Duration: {result['duration']}s\n"
        f"- Track: {result['track']}"
    )


# ======================== Render ========================


@mcp.tool()
@mcp_error_handler("VideoEdit")
async def vedit_preview(
    project_id: str,
    start: float = -1,
    end: float = -1,
    output_path: str = "",
) -> str:
    """Generate a quick preview of the timeline (or a segment). Uses ultrafast preset."""
    result = await to_thread(
        client.preview,
        project_id,
        start=start if start >= 0 else None,
        end=end if end >= 0 else None,
        output_path=output_path or None,
    )
    return f"Preview rendered: `{result['path']}`"


@mcp.tool()
@mcp_error_handler("VideoEdit")
async def vedit_render(
    project_id: str,
    output_path: str,
    vcodec: str = "libx264",
    preset: str = "medium",
    crf: int = 18,
) -> str:
    """Final render of the project to a video file. Higher quality than preview."""
    result = await to_thread(
        client.render,
        project_id,
        output_path=output_path,
        vcodec=vcodec,
        preset=preset,
        crf=crf,
    )
    return f"Rendered: `{result['path']}`"


if __name__ == "__main__":
    mcp.run()
