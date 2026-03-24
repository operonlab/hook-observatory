"""Video Edit SDK — HTTP client for Video Edit station (port 4110).

Usage:
    from workshop.clients.video_edit import VideoEditClient

    client = VideoEditClient()
    project = client.create_project("my-video")
    client.add_clip(project["id"], "/path/to/video.mp4")
    info = client.timeline_info(project["id"])
"""

import os
from typing import Any

import httpx

from workshop.port_registry import get_url


class VideoEditError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"[{status_code}] {detail}")


class VideoEditClient:
    """HTTP client for Video Edit station (port 4110)."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 30,
        render_timeout: float = 600,
    ):
        self.base_url = (
            base_url or os.environ.get("VIDEO_EDIT_URL", get_url("video-edit"))
        ).rstrip("/")
        self._timeout = timeout
        self._render_timeout = render_timeout
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(timeout=self._timeout)
        return self._client

    def close(self) -> None:
        if self._client and not self._client.is_closed:
            self._client.close()

    def _request(
        self, method: str, path: str, timeout: float | None = None, **kwargs: Any
    ) -> httpx.Response:
        url = f"{self.base_url}{path}"
        try:
            resp = self.client.request(method, url, timeout=timeout or self._timeout, **kwargs)
            resp.raise_for_status()
            return resp
        except httpx.ConnectError:
            raise VideoEditError(
                0,
                f"Cannot connect to Video Edit at {self.base_url}. "
                "Start server: cd stations/video-edit && uv run video-edit serve",
            ) from None
        except httpx.HTTPStatusError as e:
            raise VideoEditError(e.response.status_code, e.response.text[:500]) from e

    def _get(self, path: str, params: dict | None = None) -> Any:
        filtered = {k: v for k, v in params.items() if v is not None} if params else None
        return self._request("GET", path, params=filtered).json()

    def _post(self, path: str, body: dict | None = None, timeout: float | None = None) -> Any:
        return self._request("POST", path, json=body or {}, timeout=timeout).json()

    def _patch(self, path: str, body: dict | None = None) -> Any:
        return self._request("PATCH", path, json=body or {}).json()

    def _delete(self, path: str) -> Any:
        return self._request("DELETE", path).json()

    # ======================== Health ========================

    def health(self) -> dict:
        return self._get("/health")

    def is_running(self) -> bool:
        try:
            self.health()
            return True
        except Exception:
            return False

    # ======================== Projects ========================

    def list_projects(self) -> list[dict]:
        return self._get("/projects/")

    def create_project(
        self,
        name: str,
        width: int = 1920,
        height: int = 1080,
        fps_num: int = 30,
        fps_den: int = 1,
        num_tracks: int = 3,
    ) -> dict:
        return self._post(
            "/projects/",
            {
                "name": name,
                "width": width,
                "height": height,
                "fps_num": fps_num,
                "fps_den": fps_den,
                "num_tracks": num_tracks,
            },
        )

    def open_project(self, path: str) -> dict:
        return self._post("/projects/open", {"path": path})

    def get_project(self, project_id: str) -> dict:
        return self._get(f"/projects/{project_id}")

    def save_project(self, project_id: str) -> dict:
        return self._post(f"/projects/{project_id}/save")

    def timeline_info(self, project_id: str) -> dict:
        return self._get(f"/projects/{project_id}/timeline")

    # ======================== Clips ========================

    def add_clip(
        self,
        project_id: str,
        file_path: str,
        track: int = 0,
        in_point: float = 0,
        out_point: float | None = None,
    ) -> dict:
        body: dict[str, Any] = {
            "file_path": file_path,
            "track": track,
            "in_point": in_point,
        }
        if out_point is not None:
            body["out_point"] = out_point
        return self._post(f"/projects/{project_id}/clips", body)

    def cut_clip(self, project_id: str, clip_id: str, at_time: float) -> dict:
        return self._post(f"/projects/{project_id}/clips/{clip_id}/cut", {"at_time": at_time})

    def trim_clip(
        self,
        project_id: str,
        clip_id: str,
        in_point: float | None = None,
        out_point: float | None = None,
    ) -> dict:
        body: dict[str, Any] = {}
        if in_point is not None:
            body["in_point"] = in_point
        if out_point is not None:
            body["out_point"] = out_point
        return self._patch(f"/projects/{project_id}/clips/{clip_id}/trim", body)

    def remove_clip(self, project_id: str, clip_id: str) -> dict:
        return self._delete(f"/projects/{project_id}/clips/{clip_id}")

    def move_clip(
        self,
        project_id: str,
        clip_id: str,
        new_track: int | None = None,
        new_position: int | None = None,
    ) -> dict:
        body: dict[str, Any] = {}
        if new_track is not None:
            body["new_track"] = new_track
        if new_position is not None:
            body["new_position"] = new_position
        return self._patch(f"/projects/{project_id}/clips/{clip_id}/move", body)

    # ======================== Effects ========================

    def add_transition(
        self,
        project_id: str,
        a_track: int,
        b_track: int,
        transition_type: str = "luma",
        in_time: float = 0,
        out_time: float = 2,
    ) -> dict:
        return self._post(
            f"/projects/{project_id}/transitions",
            {
                "a_track": a_track,
                "b_track": b_track,
                "transition_type": transition_type,
                "in_time": in_time,
                "out_time": out_time,
            },
        )

    def add_subtitle(
        self,
        project_id: str,
        text: str,
        start: float,
        end: float,
        track: int | None = None,
        font_size: int = 48,
        color: str = "#ffffffff",
        bg_color: str = "#00000080",
        valign: str = "bottom",
    ) -> dict:
        body: dict[str, Any] = {
            "text": text,
            "start": start,
            "end": end,
            "font_size": font_size,
            "color": color,
            "bg_color": bg_color,
            "valign": valign,
        }
        if track is not None:
            body["track"] = track
        return self._post(f"/projects/{project_id}/subtitles", body)

    def add_filter(
        self,
        project_id: str,
        clip_id: str,
        filter_type: str,
        params: dict[str, str] | None = None,
    ) -> dict:
        body: dict[str, Any] = {"filter_type": filter_type}
        if params:
            body["params"] = params
        return self._post(f"/projects/{project_id}/clips/{clip_id}/filters", body)

    def adjust_audio(
        self,
        project_id: str,
        clip_id: str,
        volume: float | None = None,
        fade_in: float | None = None,
        fade_out: float | None = None,
    ) -> dict:
        body: dict[str, Any] = {}
        if volume is not None:
            body["volume"] = volume
        if fade_in is not None:
            body["fade_in"] = fade_in
        if fade_out is not None:
            body["fade_out"] = fade_out
        return self._post(f"/projects/{project_id}/clips/{clip_id}/audio", body)

    def add_image_overlay(
        self,
        project_id: str,
        file_path: str,
        start: float,
        duration: float,
        track: int = 1,
        geometry: str = "0/0:100%x100%",
        fade_in: float = 0.5,
        fade_out: float = 0.5,
        opacity: float = 1.0,
    ) -> dict:
        return self._post(
            f"/projects/{project_id}/overlays",
            {
                "file_path": file_path,
                "start": start,
                "duration": duration,
                "track": track,
                "geometry": geometry,
                "fade_in": fade_in,
                "fade_out": fade_out,
                "opacity": opacity,
            },
        )

    # ======================== Render ========================

    def preview(
        self,
        project_id: str,
        start: float | None = None,
        end: float | None = None,
        output_path: str | None = None,
    ) -> dict:
        body: dict[str, Any] = {}
        if start is not None:
            body["start"] = start
        if end is not None:
            body["end"] = end
        if output_path is not None:
            body["output_path"] = output_path
        return self._post(f"/projects/{project_id}/preview", body, timeout=self._render_timeout)

    def render(
        self,
        project_id: str,
        output_path: str,
        vcodec: str = "libx264",
        acodec: str = "aac",
        preset: str = "medium",
        crf: int = 18,
    ) -> dict:
        return self._post(
            f"/projects/{project_id}/render",
            {
                "output_path": output_path,
                "vcodec": vcodec,
                "acodec": acodec,
                "preset": preset,
                "crf": crf,
            },
            timeout=self._render_timeout,
        )

    # ======================== Context Manager ========================

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __repr__(self) -> str:
        return f"VideoEditClient(base_url={self.base_url!r})"
