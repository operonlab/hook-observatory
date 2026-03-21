"""Project management routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class CreateProjectRequest(BaseModel):
    name: str
    width: int | None = None
    height: int | None = None
    fps_num: int | None = None
    fps_den: int | None = None
    num_tracks: int = 3


class OpenProjectRequest(BaseModel):
    path: str


def _engine():
    from video_edit.main import engine
    return engine


@router.get("/")
async def list_projects():
    return _engine().list_projects()


@router.post("/")
async def create_project(req: CreateProjectRequest):
    try:
        info = _engine().create_project(
            name=req.name,
            width=req.width,
            height=req.height,
            fps_num=req.fps_num,
            fps_den=req.fps_den,
            num_tracks=req.num_tracks,
        )
        return {
            "id": info.id,
            "name": info.name,
            "path": info.path,
            "width": info.width,
            "height": info.height,
            "fps": f"{info.fps_num}/{info.fps_den}",
            "tracks": info.tracks,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/open")
async def open_project(req: OpenProjectRequest):
    try:
        info = _engine().open_project(req.path)
        return {
            "id": info.id,
            "name": info.name,
            "path": info.path,
            "width": info.width,
            "height": info.height,
            "fps": f"{info.fps_num}/{info.fps_den}",
            "tracks": info.tracks,
            "clips": len(info.clips),
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{project_id}")
async def get_project(project_id: str):
    try:
        return _engine().timeline_info(project_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{project_id}/timeline")
async def get_timeline(project_id: str):
    try:
        return _engine().timeline_info(project_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{project_id}/save")
async def save_project(project_id: str):
    try:
        path = _engine().save_project(project_id)
        return {"path": path, "saved": True}
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))
