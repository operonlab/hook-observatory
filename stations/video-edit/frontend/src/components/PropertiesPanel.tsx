import { useState, useEffect } from "react";
import type { ClipInfo } from "../types";
import { api } from "../api";
import { parseTc, friendlyName } from "../utils";

interface Props {
  clip: ClipInfo | null;
  projectId: string | null;
  onTrim: (clipId: string, inPoint: number, outPoint: number) => Promise<void>;
  onRemove: (clipId: string) => Promise<void>;
  onSeek: (time: number) => void;
}

export function PropertiesPanel({
  clip,
  projectId,
  onTrim,
  onRemove,
  onSeek,
}: Props) {
  const [startInput, setStartInput] = useState("");
  const [endInput, setEndInput] = useState("");
  const [speed, setSpeed] = useState(1.0);

  useEffect(() => {
    if (clip) {
      setStartInput(clip.timeline_start);
      setEndInput(clip.timeline_end);
      setSpeed(1.0);
    }
  }, [clip]);

  if (!clip || !projectId) {
    return (
      <div className="border-t border-white/10 bg-surface-1 px-4 py-3">
        <p className="text-xs text-white/30">
          點擊時間軸上的 block 來編輯
        </p>
      </div>
    );
  }

  const duration = parseTc(clip.timeline_end) - parseTc(clip.timeline_start);

  const handleApply = async () => {
    const newIn = parseTc(startInput);
    const newEnd = parseTc(endInput);
    if (isNaN(newIn) || isNaN(newEnd) || newEnd <= newIn) {
      alert("時間值無效");
      return;
    }
    await onTrim(clip.clip_id, newIn, newEnd);
  };

  const handleRemove = async () => {
    if (confirm(`確定刪除 ${friendlyName(clip.resource)}？`)) {
      await onRemove(clip.clip_id);
    }
  };

  return (
    <div className="border-t border-white/10 bg-surface-1 px-4 py-3">
      <div className="mb-2 text-sm font-semibold text-gold">
        {friendlyName(clip.resource)}
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <div>
          <label className="text-[11px] text-white/40">Start</label>
          <input
            className="w-full rounded border border-white/10 bg-surface-0 px-2 py-1 text-xs tabular-nums text-white focus:border-accent focus:outline-none"
            value={startInput}
            onChange={(e) => setStartInput(e.target.value)}
          />
        </div>
        <div>
          <label className="text-[11px] text-white/40">End</label>
          <input
            className="w-full rounded border border-white/10 bg-surface-0 px-2 py-1 text-xs tabular-nums text-white focus:border-accent focus:outline-none"
            value={endInput}
            onChange={(e) => setEndInput(e.target.value)}
          />
        </div>
        <div>
          <label className="text-[11px] text-white/40">Duration</label>
          <div className="py-1 text-xs tabular-nums text-white/70">
            {duration.toFixed(1)}s
          </div>
        </div>
        <div>
          <label className="text-[11px] text-white/40">Resource</label>
          <div className="break-all py-1 text-[11px] text-white/50">
            {clip.resource}
          </div>
        </div>
      </div>

      {/* Speed control */}
      <div className="mt-2 flex items-center gap-2">
        <label className="w-12 text-[10px] text-white/40">Speed:</label>
        <input
          type="range"
          min="0.25"
          max="4"
          step="0.25"
          value={speed}
          onChange={async (e) => {
            const newSpeed = parseFloat(e.target.value);
            setSpeed(newSpeed);
            if (!projectId || !clip) return;
            try {
              await api.setSpeed(projectId, clip.clip_id, { speed: newSpeed });
            } catch {
              /* ignore */
            }
          }}
          className="h-1 flex-1"
        />
        <span className="w-8 text-right text-[10px] text-white/50">{speed.toFixed(2)}x</span>
      </div>

      <div className="mt-2.5 flex gap-2">
        <button
          onClick={handleApply}
          className="rounded bg-accent/20 px-3 py-1 text-xs font-medium text-accent hover:bg-accent/30"
        >
          套用變更
        </button>
        <button
          onClick={() => onSeek(parseTc(clip.timeline_start))}
          className="rounded border border-white/10 bg-surface-2 px-3 py-1 text-xs text-white/60 hover:text-white/80"
        >
          跳轉至起點
        </button>
        <button
          onClick={handleRemove}
          className="ml-auto rounded border border-red-500/30 bg-red-500/10 px-3 py-1 text-xs text-red-400 hover:bg-red-500/20"
        >
          刪除
        </button>
      </div>
    </div>
  );
}
