"""Media routes — frame render, waveform, thumbnails, streaming."""

from __future__ import annotations

from asyncio import to_thread

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response, FileResponse

router = APIRouter()


def _engine():
    from video_edit.main import engine
    return engine


@router.get("/projects/{project_id}/frame")
async def render_frame(
    project_id: str,
    time: float = Query(default=0, description="Time in seconds"),
    w: int = Query(default=960, description="Width"),
    h: int = Query(default=540, description="Height"),
):
    """Render a single frame at the given time as JPEG."""
    try:
        jpeg_bytes = await to_thread(_engine().render_frame, project_id, time, w, h)
        return Response(content=jpeg_bytes, media_type="image/jpeg")
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (RuntimeError, FileNotFoundError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_id}/clips/{clip_id}/waveform")
async def get_waveform(
    project_id: str,
    clip_id: str,
    samples: int = Query(default=800, description="Number of peak samples"),
):
    """Get audio waveform peaks for a clip."""
    try:
        peaks = await to_thread(_engine().get_waveform, project_id, clip_id, samples)
        return {"clip_id": clip_id, "samples": len(peaks), "peaks": peaks}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/projects/{project_id}/clips/{clip_id}/thumbnails")
async def get_thumbnails(
    project_id: str,
    clip_id: str,
    interval: float = Query(default=2.0, description="Seconds between thumbnails"),
):
    """Get thumbnail sprite sheet for a clip."""
    try:
        path = await to_thread(
            _engine().get_thumbnails, project_id, clip_id, interval
        )
        return FileResponse(path, media_type="image/png")
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (FileNotFoundError, RuntimeError) as e:
        raise HTTPException(status_code=500, detail=str(e))
