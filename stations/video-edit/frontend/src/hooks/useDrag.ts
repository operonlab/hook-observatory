import { useRef, useCallback } from "react";

export type DragMode = "move" | "trim-left" | "trim-right";

interface DragState {
  mode: DragMode;
  clipId: string;
  startX: number;
  origLeft: number;
  origWidth: number;
  origTimelineStart: number;
  origTimelineEnd: number;
  trackIndex: number;
  element: HTMLElement;
}

interface UseDragOpts {
  pxPerSec: number;
  trackHeight: number;
  onMoveEnd: (
    clipId: string,
    newTimeSec: number,
    newTrack?: number,
  ) => Promise<void>;
  onTrimLeftEnd: (clipId: string, newInSec: number) => Promise<void>;
  onTrimRightEnd: (clipId: string, newOutSec: number) => Promise<void>;
}

export function useDrag(opts: UseDragOpts) {
  const dragRef = useRef<DragState | null>(null);

  const onPointerDown = useCallback(
    (
      e: React.PointerEvent,
      clipId: string,
      mode: DragMode,
      timelineStart: number,
      timelineEnd: number,
      trackIndex: number,
    ) => {
      e.preventDefault();
      e.stopPropagation();
      const el = (e.target as HTMLElement).closest(
        "[data-clip-id]",
      ) as HTMLElement;
      if (!el) return;

      el.setPointerCapture(e.pointerId);

      dragRef.current = {
        mode,
        clipId,
        startX: e.clientX,
        origLeft: el.offsetLeft,
        origWidth: el.offsetWidth,
        origTimelineStart: timelineStart,
        origTimelineEnd: timelineEnd,
        trackIndex,
        element: el,
      };

      el.style.opacity = "0.8";
      el.style.zIndex = "100";
      if (mode === "move") el.style.cursor = "grabbing";
    },
    [],
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent) => {
      const d = dragRef.current;
      if (!d) return;

      const dx = e.clientX - d.startX;

      if (d.mode === "move") {
        d.element.style.left = `${d.origLeft + dx}px`;
      } else if (d.mode === "trim-left") {
        const newLeft = d.origLeft + dx;
        const newWidth = d.origWidth - dx;
        if (newWidth > 4) {
          d.element.style.left = `${newLeft}px`;
          d.element.style.width = `${newWidth}px`;
        }
      } else if (d.mode === "trim-right") {
        const newWidth = d.origWidth + dx;
        if (newWidth > 4) {
          d.element.style.width = `${newWidth}px`;
        }
      }
    },
    [],
  );

  const onPointerUp = useCallback(
    async (e: React.PointerEvent) => {
      const d = dragRef.current;
      if (!d) return;

      dragRef.current = null;
      d.element.style.opacity = "";
      d.element.style.zIndex = "";
      d.element.style.cursor = "";

      const dx = e.clientX - d.startX;
      const deltaSec = dx / opts.pxPerSec;

      try {
        if (d.mode === "move") {
          const newTime = Math.max(0, d.origTimelineStart + deltaSec);
          await opts.onMoveEnd(d.clipId, newTime);
        } else if (d.mode === "trim-left") {
          const newIn = Math.max(0, d.origTimelineStart + deltaSec);
          await opts.onTrimLeftEnd(d.clipId, newIn);
        } else if (d.mode === "trim-right") {
          const newOut = Math.max(0, d.origTimelineEnd + deltaSec);
          await opts.onTrimRightEnd(d.clipId, newOut);
        }
      } catch {
        // Revert on API failure
        d.element.style.left = `${d.origLeft}px`;
        d.element.style.width = `${d.origWidth}px`;
      }
    },
    [opts],
  );

  return { onPointerDown, onPointerMove, onPointerUp };
}
