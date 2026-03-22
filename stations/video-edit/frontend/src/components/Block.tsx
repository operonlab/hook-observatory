import { useCallback } from "react";
import type { DragMode } from "../hooks/useDrag";
import { friendlyName, trackColor } from "../utils";

interface Props {
  clipId: string;
  resource: string;
  timelineStart: number;
  timelineEnd: number;
  trackIndex: number;
  pxPerSec: number;
  isSelected: boolean;
  onSelect: (clipId: string) => void;
  onDragStart: (
    e: React.PointerEvent,
    clipId: string,
    mode: DragMode,
    timelineStart: number,
    timelineEnd: number,
    trackIndex: number,
  ) => void;
}

export function Block({
  clipId,
  resource,
  timelineStart,
  timelineEnd,
  trackIndex,
  pxPerSec,
  isSelected,
  onSelect,
  onDragStart,
}: Props) {
  const left = timelineStart * pxPerSec;
  const width = Math.max((timelineEnd - timelineStart) * pxPerSec, 4);
  const color = trackColor(trackIndex);

  const handlePointerDown = useCallback(
    (e: React.PointerEvent) => {
      onSelect(clipId);
      onDragStart(e, clipId, "move", timelineStart, timelineEnd, trackIndex);
    },
    [clipId, onSelect, onDragStart, timelineStart, timelineEnd, trackIndex],
  );

  const handleTrimLeft = useCallback(
    (e: React.PointerEvent) => {
      e.stopPropagation();
      onSelect(clipId);
      onDragStart(
        e,
        clipId,
        "trim-left",
        timelineStart,
        timelineEnd,
        trackIndex,
      );
    },
    [clipId, onSelect, onDragStart, timelineStart, timelineEnd, trackIndex],
  );

  const handleTrimRight = useCallback(
    (e: React.PointerEvent) => {
      e.stopPropagation();
      onSelect(clipId);
      onDragStart(
        e,
        clipId,
        "trim-right",
        timelineStart,
        timelineEnd,
        trackIndex,
      );
    },
    [clipId, onSelect, onDragStart, timelineStart, timelineEnd, trackIndex],
  );

  return (
    <div
      data-clip-id={clipId}
      className="absolute top-1.5 flex cursor-grab select-none items-center overflow-hidden text-ellipsis whitespace-nowrap rounded px-1.5 text-[10px] transition-[outline]"
      style={{
        left: `${left}px`,
        width: `${width}px`,
        height: "calc(48px - 12px)",
        background: color.bg,
        border: `1px solid ${color.border}`,
        outline: isSelected ? "2px solid #e2b714" : "none",
      }}
      onPointerDown={handlePointerDown}
      title={`${friendlyName(resource)}\n${timelineStart.toFixed(1)}s → ${timelineEnd.toFixed(1)}s`}
    >
      {/* Resize handle left */}
      <div
        className="absolute left-[-2px] top-0 bottom-0 z-10 cursor-ew-resize"
        style={{ width: "8px" }}
        onPointerDown={handleTrimLeft}
      />

      <span className="pointer-events-none">{friendlyName(resource)}</span>

      {/* Resize handle right */}
      <div
        className="absolute right-[-2px] top-0 bottom-0 z-10 cursor-ew-resize"
        style={{ width: "8px" }}
        onPointerDown={handleTrimRight}
      />
    </div>
  );
}
