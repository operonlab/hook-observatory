import { create } from "zustand";
import { immer } from "zustand/middleware/immer";
import { api } from "../api";
import type { TimelineInfo, ClipInfo } from "../types";

interface ProjectState {
  projectId: string | null;
  projectName: string | null;
  timeline: TimelineInfo | null;
  loading: boolean;
  error: string | null;
  saving: boolean;
}

interface ProjectActions {
  loadProject: (id: string, name: string) => Promise<void>;
  reloadTimeline: () => Promise<void>;
  save: () => Promise<void>;
  findClip: (clipId: string) => ClipInfo | null;
  optimisticUpdateClip: (
    clipId: string,
    updater: (clip: ClipInfo) => void,
  ) => void;
  reset: () => void;
}

const initialState: ProjectState = {
  projectId: null,
  projectName: null,
  timeline: null,
  loading: false,
  error: null,
  saving: false,
};

export const useProjectStore = create<ProjectState & ProjectActions>()(
  immer((set, get) => ({
    ...initialState,

    loadProject: async (id, name) => {
      set((s) => {
        s.projectId = id;
        s.projectName = name;
        s.loading = true;
        s.error = null;
        s.timeline = null;
      });
      try {
        const data = await api.getTimeline(id);
        set((s) => {
          s.timeline = data;
          s.loading = false;
        });
      } catch (e) {
        set((s) => {
          s.error = e instanceof Error ? e.message : String(e);
          s.loading = false;
        });
      }
    },

    reloadTimeline: async () => {
      const { projectId } = get();
      if (!projectId) return;
      try {
        const data = await api.getTimeline(projectId);
        set((s) => {
          s.timeline = data;
        });
      } catch {
        /* keep stale data on refresh failure */
      }
    },

    save: async () => {
      const { projectId } = get();
      if (!projectId) return;
      set((s) => {
        s.saving = true;
      });
      try {
        await api.saveProject(projectId);
      } catch (err) {
        console.error("Save failed:", err);
      } finally {
        set((s) => {
          s.saving = false;
        });
      }
    },

    findClip: (clipId) => {
      const { timeline } = get();
      if (!timeline) return null;
      for (const track of timeline.tracks) {
        const found = track.clips.find((c) => c.clip_id === clipId);
        if (found) return found;
      }
      return null;
    },

    optimisticUpdateClip: (clipId, updater) => {
      set((s) => {
        if (!s.timeline) return;
        for (const track of s.timeline.tracks) {
          const clip = track.clips.find((c) => c.clip_id === clipId);
          if (clip) {
            updater(clip);
            return;
          }
        }
      });
    },

    reset: () => set(initialState),
  })),
);
