import type {
  Project,
  ProjectInfo,
  CreateProjectReq,
  SaveResult,
  TimelineInfo,
  AddClipReq,
  TrimClipReq,
  MoveClipReq,
  MoveClipToTimeReq,
  AddTransitionReq,
  AddSubtitleReq,
  AddFilterReq,
  FilterInfo,
  AdjustAudioReq,
  AddOverlayReq,
  PreviewReq,
  RenderReq,
  WaveformData,
} from "./types";

const BASE =
  window.location.pathname.match(/^(\/apps\/mlt-editor)\/?/)?.[1] ?? "";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* ignore parse errors */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json();
}

function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: "POST", body: JSON.stringify(body) });
}

function patch<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
}

function del<T>(path: string): Promise<T> {
  return request<T>(path, { method: "DELETE" });
}

export const api = {
  // Health
  health: () => request<{ status: string }>("/health"),

  // Projects
  listProjects: () => request<Project[]>("/projects/"),
  createProject: (data: CreateProjectReq) =>
    post<ProjectInfo>("/projects/", data),
  openProject: (path: string) =>
    post<ProjectInfo>("/projects/open", { path }),
  getProject: (id: string) => request<TimelineInfo>(`/projects/${id}`),
  getTimeline: (id: string) =>
    request<TimelineInfo>(`/projects/${id}/timeline`),
  saveProject: (id: string) => post<SaveResult>(`/projects/${id}/save`, {}),

  // Clips
  addClip: (pid: string, data: AddClipReq) =>
    post(`/projects/${pid}/clips`, data),
  cutClip: (pid: string, clipId: string, atTime: number) =>
    post(`/projects/${pid}/clips/${clipId}/cut`, { at_time: atTime }),
  trimClip: (pid: string, clipId: string, data: TrimClipReq) =>
    patch(`/projects/${pid}/clips/${clipId}/trim`, data),
  removeClip: (pid: string, clipId: string) =>
    del(`/projects/${pid}/clips/${clipId}`),
  moveClip: (pid: string, clipId: string, data: MoveClipReq) =>
    patch(`/projects/${pid}/clips/${clipId}/move`, data),
  moveClipToTime: (pid: string, clipId: string, data: MoveClipToTimeReq) =>
    patch(`/projects/${pid}/clips/${clipId}/move-to-time`, data),

  // Effects
  addTransition: (pid: string, data: AddTransitionReq) =>
    post(`/projects/${pid}/transitions`, data),
  addSubtitle: (pid: string, data: AddSubtitleReq) =>
    post(`/projects/${pid}/subtitles`, data),
  addFilter: (pid: string, clipId: string, data: AddFilterReq) =>
    post(`/projects/${pid}/clips/${clipId}/filters`, data),
  listFilters: (pid: string, clipId: string) =>
    request<FilterInfo[]>(`/projects/${pid}/clips/${clipId}/filters`),
  removeFilter: (pid: string, clipId: string, filterId: string) =>
    del(`/projects/${pid}/clips/${clipId}/filters/${filterId}`),
  adjustAudio: (pid: string, clipId: string, data: AdjustAudioReq) =>
    post(`/projects/${pid}/clips/${clipId}/audio`, data),
  addOverlay: (pid: string, data: AddOverlayReq) =>
    post(`/projects/${pid}/overlays`, data),

  // Media
  renderFrame: (pid: string, time: number, w = 960, h = 540) =>
    fetch(`${BASE}/projects/${pid}/frame?time=${time}&w=${w}&h=${h}`, {
      credentials: "include",
    }).then((r) => {
      if (!r.ok) throw new ApiError(r.status, r.statusText);
      return r.blob();
    }),
  getWaveform: (pid: string, clipId: string, samples = 800) =>
    request<WaveformData>(
      `/projects/${pid}/clips/${clipId}/waveform?samples=${samples}`,
    ),
  getThumbnails: (pid: string, clipId: string, interval = 2) =>
    fetch(
      `${BASE}/projects/${pid}/clips/${clipId}/thumbnails?interval=${interval}`,
      { credentials: "include" },
    ).then((r) => {
      if (!r.ok) throw new ApiError(r.status, r.statusText);
      return r.blob();
    }),

  // Render
  preview: (pid: string, data?: PreviewReq) =>
    post(`/projects/${pid}/preview`, data ?? {}),
  render: (pid: string, data: RenderReq) =>
    post(`/projects/${pid}/render`, data),
};
