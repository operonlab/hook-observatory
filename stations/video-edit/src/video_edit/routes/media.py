"""Media streaming route — serve clip resources from MLT project."""

from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()

# Cache dir for transcoded files
_TRANSCODE_CACHE = Path.home() / "workshop" / "outputs" / "video-edit" / "transcode_cache"
_TRANSCODE_CACHE.mkdir(parents=True, exist_ok=True)


def _engine():
    from video_edit.main import engine

    return engine


def _resolve_resource(project_id: str, clip_id: str) -> Path:
    """Look up a clip's resource path from the MLT XML."""
    eng = _engine()
    try:
        root = eng._get_root(project_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    for producer in root.findall("producer"):
        pid = producer.get("id", "")
        found_clip_id = ""
        found_resource = ""
        for prop in producer.findall("property"):
            if prop.get("name") == "clip_id":
                found_clip_id = prop.text or ""
            if prop.get("name") == "resource":
                found_resource = prop.text or ""
        if (found_clip_id == clip_id or pid == clip_id) and found_resource:
            file_path = Path(found_resource)
            if not file_path.is_file():
                raise HTTPException(
                    status_code=404, detail=f"Media file not found: {file_path.name}"
                )
            return file_path

    raise HTTPException(status_code=404, detail=f"Clip {clip_id} not found or has no resource")


def _is_browser_compatible(source: Path) -> bool:
    """Check if a video file is already browser-compatible (H.264 yuv420p)."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name,pix_fmt",
                "-of",
                "csv=p=0",
                str(source),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split(",")
            codec = parts[0] if len(parts) > 0 else ""
            pix = parts[1] if len(parts) > 1 else ""
            # H.264 with yuv420p is universally supported
            return codec == "h264" and pix == "yuv420p"
    except Exception:
        pass
    return False


def _ensure_browser_compatible(source: Path) -> Path:
    """Transcode to browser-compatible format if needed. Skips if already compatible."""
    if source.suffix.lower() not in (".mov", ".mkv", ".avi"):
        return source

    # Quick probe: skip transcode if already H.264 yuv420p
    if _is_browser_compatible(source):
        return source

    cache_name = f"{source.stem}_{hash(str(source)) & 0xFFFFFFFF:08x}.mp4"
    cached = _TRANSCODE_CACHE / cache_name

    # Use cached version if source hasn't changed
    if cached.is_file() and cached.stat().st_mtime >= source.stat().st_mtime:
        return cached

    # Re-encode to H.264 yuv420p
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(source),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-preset",
                "ultrafast",
                "-crf",
                "18",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(cached),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if cached.is_file() and cached.stat().st_size > 0:
            return cached
    except Exception:
        pass

    # If transcode failed, return original
    return source


@router.get("/projects/{project_id}/clips/{clip_id}/thumbnail")
async def clip_thumbnail(project_id: str, clip_id: str):
    """Extract a single frame from a clip as PNG (preserves alpha for overlays)."""
    from asyncio import to_thread

    source = _resolve_resource(project_id, clip_id)

    # Cache thumbnail
    cache_name = f"{source.stem}_{hash(str(source)) & 0xFFFFFFFF:08x}_thumb.png"
    cached = _TRANSCODE_CACHE / cache_name

    if cached.is_file() and cached.stat().st_mtime >= source.stat().st_mtime:
        return FileResponse(cached, media_type="image/png")

    def _extract():
        # Extract frame from 50% duration (to get a representative frame, not the fade-in start)
        # First get duration
        dur = 5.0  # default
        try:
            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(source),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if probe.returncode == 0 and probe.stdout.strip():
                dur = float(probe.stdout.strip())
        except Exception:
            pass

        # Extract frame at 50% with alpha preserved
        seek_time = dur * 0.5
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(seek_time),
                "-i",
                str(source),
                "-vframes",
                "1",
                "-pix_fmt",
                "rgba",
                str(cached),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return cached

    result = await to_thread(_extract)
    if result.is_file():
        return FileResponse(result, media_type="image/png")
    raise HTTPException(status_code=500, detail="Failed to extract thumbnail")


@router.get("/projects/{project_id}/clips/{clip_id}/stream")
async def stream_clip(project_id: str, clip_id: str):
    """Stream a clip's media file, transcoding to MP4 if needed for browser compatibility."""
    from asyncio import to_thread

    source = _resolve_resource(project_id, clip_id)
    # Run transcode check in thread to avoid blocking event loop
    playable = await to_thread(_ensure_browser_compatible, source)

    suffix = playable.suffix.lower()
    media_types = {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".aac": "audio/aac",
    }
    media_type = media_types.get(suffix, "application/octet-stream")

    return FileResponse(playable, media_type=media_type)


@router.get("/projects/{project_id}/preview/stream")
async def stream_preview(project_id: str):
    """Stream the latest preview render for a project."""
    from video_edit.config import settings

    preview_path = Path(settings.PREVIEW_DIR) / f"{project_id}_preview.mp4"
    if not preview_path.is_file():
        raise HTTPException(
            status_code=404, detail="No preview available. Click 'Preview' to render one."
        )

    return FileResponse(preview_path, media_type="video/mp4")
