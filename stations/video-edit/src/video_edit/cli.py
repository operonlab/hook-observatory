"""Video Edit CLI — serve + project management commands."""

from __future__ import annotations

import click


@click.group()
def main():
    """Video Edit — MLT-based non-linear video editing station."""
    pass


@main.command()
@click.option("--host", default="127.0.0.1", help="Bind host")
@click.option("--port", type=int, default=4110, help="Bind port")
def serve(host: str, port: int):
    """Start the Video Edit API server."""
    import uvicorn

    uvicorn.run("video_edit.main:app", host=host, port=port, reload=False)


@main.group("project")
def project_group():
    """Project management commands."""
    pass


@project_group.command("list")
def project_list():
    """List all projects."""
    from video_edit.mlt_engine import MLTEngine

    engine = MLTEngine()
    projects = engine.list_projects()
    if not projects:
        click.echo("No projects found.")
        return
    for p in projects:
        click.echo(f"  {p['name']}  →  {p['path']}")


@project_group.command("create")
@click.argument("name")
@click.option("--resolution", default="1920x1080", help="WxH resolution")
@click.option("--fps", type=int, default=30, help="Frames per second")
@click.option("--tracks", type=int, default=3, help="Number of tracks")
def project_create(name: str, resolution: str, fps: int, tracks: int):
    """Create a new video editing project."""
    from video_edit.mlt_engine import MLTEngine

    w, h = resolution.split("x")
    engine = MLTEngine()
    info = engine.create_project(name, width=int(w), height=int(h), fps_num=fps, num_tracks=tracks)
    click.echo(f"Created: {info.name} ({info.width}x{info.height} @ {info.fps_num}fps)")
    click.echo(f"  Path: {info.path}")
    click.echo(f"  ID: {info.id}")


@project_group.command("info")
@click.argument("path")
def project_info(path: str):
    """Show project timeline info."""
    import json

    from video_edit.mlt_engine import MLTEngine

    engine = MLTEngine()
    info = engine.open_project(path)
    timeline = engine.timeline_info(info.id)
    click.echo(json.dumps(timeline, ensure_ascii=False, indent=2))
