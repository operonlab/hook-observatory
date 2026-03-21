"""Timeline editing routes — add, cut, trim, remove, move clips."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class AddClipRequest(BaseModel):
    file_path: str
    track: int = 0
    in_point: float = 0
    out_point: float | None = None


class CutClipRequest(BaseModel):
    at_time: float


class TrimClipRequest(BaseModel):
    in_point: float | None = None
    out_point: float | None = None


class MoveClipRequest(BaseModel):
    new_track: int | None = None
    new_position: int | None = None


def _engine():
    from video_edit.main import engine
    return engine


@router.post("/projects/{project_id}/clips")
async def add_clip(project_id: str, req: AddClipRequest):
    try:
        return _engine().add_clip(
            project_id,
            file_path=req.file_path,
            track=req.track,
            in_point=req.in_point,
            out_point=req.out_point,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/projects/{project_id}/clips/{clip_id}/cut")
async def cut_clip(project_id: str, clip_id: str, req: CutClipRequest):
    try:
        return _engine().cut_clip(project_id, clip_id, req.at_time)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/projects/{project_id}/clips/{clip_id}/trim")
async def trim_clip(project_id: str, clip_id: str, req: TrimClipRequest):
    try:
        return _engine().trim_clip(project_id, clip_id, req.in_point, req.out_point)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/projects/{project_id}/clips/{clip_id}")
async def remove_clip(project_id: str, clip_id: str):
    try:
        return _engine().remove_clip(project_id, clip_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/projects/{project_id}/clips/{clip_id}/move")
async def move_clip(project_id: str, clip_id: str, req: MoveClipRequest):
    try:
        return _engine().move_clip(project_id, clip_id, req.new_track, req.new_position)
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
