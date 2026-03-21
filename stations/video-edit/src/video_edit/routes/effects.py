"""Effects routes — transitions, subtitles, filters, audio."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class AddTransitionRequest(BaseModel):
    a_track: int
    b_track: int
    transition_type: str = "luma"
    in_time: float = 0
    out_time: float = 2


class AddSubtitleRequest(BaseModel):
    text: str
    start: float
    end: float
    track: int | None = None
    font_size: int = 48
    color: str = "#ffffffff"
    bg_color: str = "#00000080"
    valign: str = "bottom"


class AddFilterRequest(BaseModel):
    filter_type: str
    params: dict[str, str] | None = None


class AdjustAudioRequest(BaseModel):
    volume: float | None = None
    fade_in: float | None = None
    fade_out: float | None = None


def _engine():
    from video_edit.main import engine
    return engine


@router.post("/projects/{project_id}/transitions")
async def add_transition(project_id: str, req: AddTransitionRequest):
    try:
        return _engine().add_transition(
            project_id,
            a_track=req.a_track,
            b_track=req.b_track,
            transition_type=req.transition_type,
            in_time=req.in_time,
            out_time=req.out_time,
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/projects/{project_id}/subtitles")
async def add_subtitle(project_id: str, req: AddSubtitleRequest):
    try:
        return _engine().add_subtitle(
            project_id,
            text=req.text,
            start=req.start,
            end=req.end,
            track=req.track,
            font_size=req.font_size,
            color=req.color,
            bg_color=req.bg_color,
            valign=req.valign,
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/projects/{project_id}/clips/{clip_id}/filters")
async def add_filter(project_id: str, clip_id: str, req: AddFilterRequest):
    try:
        return _engine().add_filter(project_id, clip_id, req.filter_type, req.params)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/projects/{project_id}/clips/{clip_id}/audio")
async def adjust_audio(project_id: str, clip_id: str, req: AdjustAudioRequest):
    try:
        return _engine().adjust_audio(
            project_id, clip_id, req.volume, req.fade_in, req.fade_out
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
