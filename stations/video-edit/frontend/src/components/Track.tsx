import type { ClipInfo } from "../types";
import type { DragMode } from "../hooks/useDrag";
import { Block } from "./Block";
import { parseTc, trackColor } from "../utils";

interface Props {
  trackId: string;
  trackIndex: number;
  clips: ClipInfo[];
  pxPerSec: number;
  selectedClipId: string | null;
  projectId: string | null;
  onSelectClip: (clipId: string, event?: React.PointerEvent) => void;
  onDragStart: (
    e: React.PointerEvent,
    clipId: string,
    mode: DragMode,
    timelineStart: number,
    timelineEnd: number,
    trackIndex: number,
  ) => void;
}

export function Track({
  trackId,
  trackIndex,
  clips,
  pxPerSec,
  selectedClipId,
  projectId,
  onSelectClip,
  onDragStart,
}: Props) {
  const color = trackColor(trackIndex);

  return (
    <div
      className="relative border-b border-white/5"
      style={{ height: "48px" }}
    >
      {/* Track label */}
      <div className="sticky left-0 z-10 flex h-full w-20 items-center border-r border-white/10 bg-surface-0 pl-2 text-[11px] text-white/40">
        {color.label || trackId}
      </div>

      {/* Track content */}
      <div className="absolute top-0 right-0 left-20 h-full">
        {clips.map((clip) => {
          const start = parseTc(clip.timeline_start);
          const end = parseTc(clip.timeline_end);
          return (
            <Block
              key={clip.clip_id}
              clipId={clip.clip_id}
              resource={clip.resource}
              timelineStart={start}
              timelineEnd={end}
              trackIndex={trackIndex}
              pxPerSec={pxPerSec}
              isSelected={clip.clip_id === selectedClipId}
              projectId={projectId}
              onSelect={onSelectClip}
              onDragStart={onDragStart}
            />
          );
        })}
      </div>
    </div>
  );
}
