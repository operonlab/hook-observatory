// Timeline replay store (C6)

import { create } from 'zustand';
import { timelineRecorder, type TimelineFrame } from '../engine/TimelineRecorder';

interface TimelineState {
  /** Whether replay mode is active */
  replaying: boolean;
  /** Current frame index during replay */
  currentIndex: number;
  /** Playback speed (1 = real-time, 2 = 2x, etc.) */
  speed: number;
  /** Whether playback is paused */
  paused: boolean;
  /** Total frame count (cached for reactivity) */
  frameCount: number;

  startReplay: () => void;
  stopReplay: () => void;
  togglePause: () => void;
  setSpeed: (s: number) => void;
  seekTo: (index: number) => void;
  tick: () => void;
  updateFrameCount: () => void;
}

export const useTimelineStore = create<TimelineState>((set, get) => ({
  replaying: false,
  currentIndex: 0,
  speed: 1,
  paused: false,
  frameCount: 0,

  startReplay() {
    const count = timelineRecorder.frameCount;
    if (count < 2) return; // need at least 2 frames
    timelineRecorder.pause();
    set({ replaying: true, currentIndex: 0, paused: false, frameCount: count });
  },

  stopReplay() {
    timelineRecorder.resume();
    set({ replaying: false, currentIndex: 0, paused: false });
  },

  togglePause() {
    set({ paused: !get().paused });
  },

  setSpeed(s) {
    set({ speed: Math.max(0.5, Math.min(8, s)) });
  },

  seekTo(index) {
    const count = timelineRecorder.frameCount;
    set({ currentIndex: Math.max(0, Math.min(count - 1, index)) });
  },

  tick() {
    const { replaying, paused, currentIndex, speed } = get();
    if (!replaying || paused) return;

    const count = timelineRecorder.frameCount;
    const next = currentIndex + speed;
    if (next >= count - 1) {
      // Reached end — loop back or stop
      set({ currentIndex: 0 }); // loop
    } else {
      set({ currentIndex: Math.floor(next) });
    }
  },

  updateFrameCount() {
    set({ frameCount: timelineRecorder.frameCount });
  },
}));

/** Get current replay frame (or null if not replaying) */
export function getReplayFrame(): TimelineFrame | null {
  const { replaying, currentIndex } = useTimelineStore.getState();
  if (!replaying) return null;
  return timelineRecorder.getFrame(currentIndex);
}
