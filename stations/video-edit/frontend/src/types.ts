// --- Projects ---

export interface Project {
  name: string;
  path: string;
  modified: string;
}

export interface ProjectInfo {
  id: string;
  name: string;
  path: string;
  width: number;
  height: number;
  fps_num: number;
  fps_den: number;
  tracks: number;
}

export interface CreateProjectReq {
  name: string;
  width?: number;
  height?: number;
  fps_num?: number;
  fps_den?: number;
  num_tracks?: number;
}

export interface OpenProjectReq {
  path: string;
}

export interface SaveResult {
  path: string;
  saved: boolean;
}

// --- Timeline ---

export interface Profile {
  width: string | null;
  height: string | null;
  fps: string | null;
}

export interface ClipInfo {
  clip_id: string;
  resource: string;
  in: string;
  out: string;
  timeline_start: string;
  timeline_end: string;
}

export interface TrackInfo {
  track: string;
  clips: ClipInfo[];
}

export interface TransitionInfo {
  id: string;
  type: string;
  a_track: string;
  b_track: string;
  in: string;
  out: string;
}

export interface TimelineInfo {
  profile: Profile;
  tracks: TrackInfo[];
  transitions: TransitionInfo[];
}

// --- Clips ---

export interface AddClipReq {
  file_path: string;
  track?: number;
  in_point?: number;
  out_point?: number;
}

export interface CutClipReq {
  at_time: number;
}

export interface TrimClipReq {
  in_point?: number;
  out_point?: number;
}

export interface MoveClipReq {
  new_track?: number;
  new_position?: number;
}

export interface MoveClipToTimeReq {
  target_time: number;
  target_track?: number;
}

// --- Effects ---

export interface AddTransitionReq {
  a_track: number;
  b_track: number;
  transition_type?: string;
  in_time?: number;
  out_time?: number;
}

export interface AddSubtitleReq {
  text: string;
  start: number;
  end: number;
  track?: number;
  font_size?: number;
  color?: string;
  bg_color?: string;
  valign?: string;
}

export interface AddFilterReq {
  filter_type: string;
  params?: Record<string, string>;
}

export interface FilterInfo {
  filter_id: string;
  type: string;
  params: Record<string, string>;
}

export interface AdjustAudioReq {
  volume?: number;
  fade_in?: number;
  fade_out?: number;
}

export interface AddOverlayReq {
  file_path: string;
  start: number;
  duration: number;
  track?: number;
  geometry?: string;
  fade_in?: number;
  fade_out?: number;
  opacity?: number;
}

// --- Render ---

export interface PreviewReq {
  start?: number;
  end?: number;
  output_path?: string;
}

export interface RenderReq {
  output_path: string;
  vcodec?: string;
  acodec?: string;
  preset?: string;
  crf?: number;
}

// --- Media ---

export interface WaveformData {
  clip_id: string;
  samples: number;
  peaks: number[];
}
