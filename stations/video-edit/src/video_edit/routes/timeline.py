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


class MoveClipToTimeRequest(BaseModel):
    target_time: float
    target_track: int | None = None


class SetSpeedRequest(BaseModel):
    speed: float


class SetKeyframesRequest(BaseModel):
    property_name: str
    keyframe_str: str


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


@router.patch("/projects/{project_id}/clips/{clip_id}/move-to-time")
async def move_clip_to_time(project_id: str, clip_id: str, req: MoveClipToTimeRequest):
    try:
        return _engine().move_clip_to_time(
            project_id, clip_id, req.target_time, req.target_track
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/projects/{project_id}/clips/{clip_id}/speed")
async def set_speed(project_id: str, clip_id: str, req: SetSpeedRequest):
    try:
        return _engine().set_speed(project_id, clip_id, req.speed)
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/projects/{project_id}/clips/{clip_id}/filters/{filter_id}/keyframes")
async def get_keyframes(project_id: str, clip_id: str, filter_id: str):
    try:
        return _engine().get_keyframes(project_id, clip_id, filter_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/projects/{project_id}/clips/{clip_id}/filters/{filter_id}/keyframes")
async def set_keyframes(project_id: str, clip_id: str, filter_id: str, req: SetKeyframesRequest):
    try:
        return _engine().set_keyframes(project_id, clip_id, filter_id, req.property_name, req.keyframe_str)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/projects/{project_id}/clips/{clip_id}/ripple")
async def ripple_remove(project_id: str, clip_id: str):
    try:
        return _engine().ripple_remove(project_id, clip_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
