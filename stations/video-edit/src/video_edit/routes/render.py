"""Render and preview routes."""

from __future__ import annotations

from asyncio import to_thread

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class PreviewRequest(BaseModel):
    start: float | None = None
    end: float | None = None
    output_path: str | None = None


class RenderRequest(BaseModel):
    output_path: str
    vcodec: str = "libx264"
    acodec: str = "aac"
    preset: str = "medium"
    crf: int = 18


def _engine():
    from video_edit.main import engine
    return engine


@router.post("/projects/{project_id}/preview")
async def preview(project_id: str, req: PreviewRequest):
    try:
        path = await to_thread(
            _engine().preview,
            project_id,
            start=req.start,
            end=req.end,
            output_path=req.output_path,
        )
        return {"path": path, "preview": True}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/projects/{project_id}/render")
async def render(project_id: str, req: RenderRequest):
    try:
        path = await to_thread(
            _engine().render,
            project_id,
            output_path=req.output_path,
            vcodec=req.vcodec,
            acodec=req.acodec,
            preset=req.preset,
            crf=req.crf,
        )
        return {"path": path, "rendered": True}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
