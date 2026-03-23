import { useState, useCallback } from "react";
import { api } from "../api";
import { useProjectStore } from "../stores/projectStore";

interface Props {
  beforeClipEnd: number;   // seconds
  afterClipStart: number;  // seconds
  trackIndex: number;
  pxPerSec: number;
}

const TRANSITION_TYPES = [
  { value: "luma", label: "Dissolve" },
  { value: "wipe", label: "Wipe" },
  { value: "composite", label: "Composite" },
];

export function TransitionHandle({
  beforeClipEnd,
  afterClipStart,
  trackIndex,
  pxPerSec,
}: Props) {
  const [open, setOpen] = useState(false);
  const [duration, setDuration] = useState(1.0);

  const gap = afterClipStart - beforeClipEnd;
  // Only show when clips are close (< 2 seconds gap)
  if (gap > 2 || gap < -0.5) return null;

  const left = Math.min(beforeClipEnd, afterClipStart) * pxPerSec;

  const handleAdd = useCallback(
    async (type: string) => {
      const pid = useProjectStore.getState().projectId;
      if (!pid) return;
      const inTime = beforeClipEnd - duration / 2;
      const outTime = beforeClipEnd + duration / 2;
      try {
        await api.addTransition(pid, {
          a_track: 0,
          b_track: trackIndex,
          transition_type: type,
          in_time: Math.max(0, inTime),
          out_time: outTime,
        });
        await useProjectStore.getState().reloadTimeline();
        setOpen(false);
      } catch (err) {
        console.error("Add transition failed:", err);
      }
    },
    [beforeClipEnd, duration, trackIndex],
  );

  return (
    <div
      className="absolute top-0 z-20 flex h-full items-center"
      style={{ left: `${left}px` }}
    >
      <button
        onClick={() => setOpen(!open)}
        className="flex h-5 w-5 items-center justify-center rounded-full bg-white/10 text-[10px] text-white/60 hover:bg-white/20"
        title="Add transition"
      >
        +
      </button>
      {open && (
        <div className="absolute top-6 left-0 z-30 rounded border border-white/10 bg-surface-1 p-2 shadow-lg">
          <div className="mb-1 text-[10px] text-white/40">Transition</div>
          {TRANSITION_TYPES.map((t) => (
            <button
              key={t.value}
              onClick={() => handleAdd(t.value)}
              className="block w-full rounded px-2 py-1 text-left text-[11px] text-white/70 hover:bg-white/10"
            >
              {t.label}
            </button>
          ))}
          <div className="mt-1 flex items-center gap-1">
            <span className="text-[10px] text-white/40">Duration:</span>
            <input
              type="range"
              min="0.5"
              max="3"
              step="0.1"
              value={duration}
              onChange={(e) => setDuration(parseFloat(e.target.value))}
              className="h-1 w-16"
            />
            <span className="text-[10px] text-white/50">{duration.toFixed(1)}s</span>
          </div>
        </div>
      )}
    </div>
  );
}
