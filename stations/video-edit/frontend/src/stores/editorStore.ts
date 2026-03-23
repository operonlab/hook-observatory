import { create } from "zustand";

export type ActiveTool = "select" | "cut" | "trim";
export type PlaybackState = "stopped" | "playing" | "paused";

interface EditorState {
  selectedClipIds: Set<string>;
  pxPerSec: number;
  currentTime: number;
  duration: number;
  playbackState: PlaybackState;
  activeTool: ActiveTool;
  snapEnabled: boolean;
  rippleEnabled: boolean;
}

interface EditorActions {
  selectClip: (clipId: string | null) => void;
  toggleClipSelection: (clipId: string) => void;
  clearSelection: () => void;
  setPxPerSec: (value: number) => void;
  zoom: (delta: number) => void;
  setCurrentTime: (time: number) => void;
  setDuration: (duration: number) => void;
  setPlaybackState: (state: PlaybackState) => void;
  setActiveTool: (tool: ActiveTool) => void;
  setSnapEnabled: (enabled: boolean) => void;
  setRippleEnabled: (enabled: boolean) => void;
}

export const useEditorStore = create<EditorState & EditorActions>()((set) => ({
  selectedClipIds: new Set<string>(),
  pxPerSec: 6,
  currentTime: 0,
  duration: 0,
  playbackState: "stopped",
  activeTool: "select",
  snapEnabled: true,
  rippleEnabled: false,

  selectClip: (clipId) =>
    set({ selectedClipIds: clipId ? new Set([clipId]) : new Set() }),

  toggleClipSelection: (clipId) =>
    set((s) => {
      const next = new Set(s.selectedClipIds);
      if (next.has(clipId)) next.delete(clipId);
      else next.add(clipId);
      return { selectedClipIds: next };
    }),

  clearSelection: () => set({ selectedClipIds: new Set() }),

  setPxPerSec: (value) =>
    set({ pxPerSec: Math.max(1, Math.min(20, value)) }),

  zoom: (delta) =>
    set((s) => ({
      pxPerSec: Math.max(1, Math.min(20, s.pxPerSec + delta)),
    })),

  setCurrentTime: (time) => set({ currentTime: time }),
  setDuration: (duration) => set({ duration }),
  setPlaybackState: (state) => set({ playbackState: state }),
  setActiveTool: (tool) => set({ activeTool: tool }),
  setSnapEnabled: (enabled) => set({ snapEnabled: enabled }),
  setRippleEnabled: (enabled) => set({ rippleEnabled: enabled }),
}));
