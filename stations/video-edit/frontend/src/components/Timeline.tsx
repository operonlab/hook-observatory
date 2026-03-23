import { useMemo, useRef } from "react";
import type { TimelineInfo } from "../types";
import type { DragMode } from "../hooks/useDrag";
import { Track } from "./Track";
import { Playhead } from "./Playhead";

const LABEL_OFFSET = 80;

interface Props {
  timeline: TimelineInfo;
  pxPerSec: number;
  currentTime: number;
  totalDuration: number;
  selectedClipId: string | null;
  projectId: string | null;
  onSelectClip: (clipId: string, event?: React.PointerEvent | React.MouseEvent) => void;
  onDragStart: (
    e: React.PointerEvent,
    clipId: string,
    mode: DragMode,
    timelineStart: number,
    timelineEnd: number,
    trackIndex: number,
  ) => void;
  onPointerMove: (e: React.PointerEvent) => void;
  onPointerUp: (e: React.PointerEvent) => void;
  onRulerClick: (timeSec: number) => void;
}

export function Timeline({
  timeline,
  pxPerSec,
  currentTime,
  totalDuration,
  selectedClipId,
  projectId,
  onSelectClip,
  onDragStart,
  onPointerMove,
  onPointerUp,
  onRulerClick,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const dur = totalDuration || 60;
  const timelineWidth = dur * pxPerSec + LABEL_OFFSET + 40;

  // Ruler ticks
  const rulerTicks = useMemo(() => {
    const step = pxPerSec >= 8 ? 10 : pxPerSec >= 4 ? 30 : 60;
    const ticks: { x: number; label: string }[] = [];
    for (let s = 0; s <= dur; s += step) {
      const x = LABEL_OFFSET + s * pxPerSec;
      const mm = Math.floor(s / 60);
      const ss = s % 60;
      ticks.push({
        x,
        label: `${mm}:${String(ss).padStart(2, "0")}`,
      });
    }
    return ticks;
  }, [pxPerSec, dur]);

  const handleRulerClick = (e: React.MouseEvent) => {
    const container = containerRef.current;
    if (!container) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const x =
      e.clientX - rect.left - LABEL_OFFSET + container.scrollLeft;
    const t = Math.max(0, x / pxPerSec);
    onRulerClick(t);
  };

  const trackCount = timeline.tracks.length;
  const contentHeight = 28 + trackCount * 48; // ruler + tracks

  return (
    <div
      ref={containerRef}
      className="relative overflow-x-auto overflow-y-hidden bg-surface-0"
      style={{ touchAction: "none", WebkitOverflowScrolling: "touch" }}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
    >
      <div className="relative" style={{ width: `${timelineWidth}px`, minHeight: "200px" }}>
        {/* Ruler */}
        <div
          className="relative h-7 cursor-pointer border-b border-white/10 bg-surface-1"
          onClick={handleRulerClick}
        >
          {rulerTicks.map((tick) => (
            <div key={tick.x}>
              <div
                className="absolute top-0 h-full border-l border-white/15"
                style={{ left: `${tick.x}px` }}
              />
              <div
                className="absolute top-1 whitespace-nowrap pl-1 text-[10px] text-white/30"
                style={{ left: `${tick.x}px` }}
              >
                {tick.label}
              </div>
            </div>
          ))}
        </div>

        {/* Tracks */}
        {timeline.tracks.map((track, i) => (
          <Track
            key={track.track}
            trackId={track.track}
            trackIndex={i}
            clips={track.clips}
            pxPerSec={pxPerSec}
            selectedClipId={selectedClipId}
            projectId={projectId}
            onSelectClip={onSelectClip}
            onDragStart={onDragStart}
          />
        ))}

        {/* Playhead */}
        <Playhead
          currentTime={currentTime}
          pxPerSec={pxPerSec}
          labelOffset={LABEL_OFFSET}
          height={contentHeight}
        />
      </div>
    </div>
  );
}
