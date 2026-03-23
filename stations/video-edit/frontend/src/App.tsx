import { useCallback, useMemo, useEffect } from "react";
import { AuthGuard } from "./components/AuthGuard";
import { ProjectSelector } from "./components/ProjectSelector";
import { VideoPlayer } from "./components/VideoPlayer";
import { Timeline } from "./components/Timeline";
import { PropertiesPanel } from "./components/PropertiesPanel";
import { useVideoSync } from "./hooks/useVideoSync";
import { useDrag } from "./hooks/useDrag";
import { useProjectStore } from "./stores/projectStore";
import { useEditorStore } from "./stores/editorStore";
import { useHistoryStore } from "./stores/historyStore";
import { TrimCommand, RemoveCommand, MoveToTimeCommand } from "./commands";
import { parseTc } from "./utils";
import type { ProjectInfo, ClipInfo } from "./types";

export default function App() {
  // --- Stores ---
  const projectId = useProjectStore((s) => s.projectId);
  const projectName = useProjectStore((s) => s.projectName);
  const timeline = useProjectStore((s) => s.timeline);
  const loading = useProjectStore((s) => s.loading);
  const error = useProjectStore((s) => s.error);
  const saving = useProjectStore((s) => s.saving);
  const loadProject = useProjectStore((s) => s.loadProject);
  const save = useProjectStore((s) => s.save);

  const selectedClipIds = useEditorStore((s) => s.selectedClipIds);
  const pxPerSec = useEditorStore((s) => s.pxPerSec);
  const zoom = useEditorStore((s) => s.zoom);
  const selectClip = useEditorStore((s) => s.selectClip);
  const setCurrentTime = useEditorStore((s) => s.setCurrentTime);
  const setDuration = useEditorStore((s) => s.setDuration);

  const historyUndo = useHistoryStore((s) => s.undo);
  const historyRedo = useHistoryStore((s) => s.redo);
  const executeCmd = useHistoryStore((s) => s.execute);

  // First selected clip ID (for components that take single selection)
  const selectedClipId = useMemo(() => {
    const ids = Array.from(selectedClipIds);
    return ids.length > 0 ? ids[0] : null;
  }, [selectedClipIds]);

  // --- Video sync ---
  const { videoRef, currentTime, duration, seekTo } = useVideoSync();

  // Sync video time/duration into editor store
  useEffect(() => {
    setCurrentTime(currentTime);
  }, [currentTime, setCurrentTime]);

  useEffect(() => {
    setDuration(duration);
  }, [duration, setDuration]);

  // --- Keyboard shortcuts ---
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ignore if typing in an input
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

      if (e.key === " ") {
        e.preventDefault();
        const video = videoRef.current;
        if (video) {
          if (video.paused) video.play();
          else video.pause();
        }
      }

      // Cmd+Z / Ctrl+Z = undo
      if ((e.metaKey || e.ctrlKey) && e.key === "z" && !e.shiftKey) {
        e.preventDefault();
        historyUndo();
      }

      // Cmd+Shift+Z / Ctrl+Shift+Z = redo
      if ((e.metaKey || e.ctrlKey) && e.key === "z" && e.shiftKey) {
        e.preventDefault();
        historyRedo();
      }

      // Delete / Backspace = remove selected clip(s)
      if (e.key === "Delete" || e.key === "Backspace") {
        const ids = Array.from(useEditorStore.getState().selectedClipIds);
        if (ids.length > 0 && useProjectStore.getState().projectId) {
          e.preventDefault();
          // Remove first selected, user can press Delete again for more
          handleRemove(ids[0]);
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [selectedClipId, projectId, historyUndo, historyRedo]); // eslint-disable-line react-hooks/exhaustive-deps

  // --- Handlers ---
  const handleProjectSelect = useCallback(
    async (info: ProjectInfo) => {
      selectClip(null);
      useHistoryStore.getState().clear();
      await loadProject(info.id, info.name);
    },
    [loadProject, selectClip],
  );

  // Snap points: all clip edges across all tracks
  const snapPoints = useMemo(() => {
    if (!timeline) return [];
    const pts = new Set<number>();
    for (const track of timeline.tracks) {
      for (const clip of track.clips) {
        pts.add(parseTc(clip.timeline_start));
        pts.add(parseTc(clip.timeline_end));
      }
    }
    return Array.from(pts);
  }, [timeline]);

  // Drag callbacks
  const dragCallbacks = useMemo(
    () => ({
      pxPerSec,
      trackHeight: 48,
      snapPoints,
      onMoveEnd: async (clipId: string, newTimeSec: number) => {
        const clip = useProjectStore.getState().findClip(clipId);
        if (!clip) return;
        const prevTime = parseTc(clip.timeline_start);
        const prevTrack = (() => {
          const tl = useProjectStore.getState().timeline;
          if (!tl) return 0;
          for (let i = 0; i < tl.tracks.length; i++) {
            if (tl.tracks[i].clips.some((c) => c.clip_id === clipId)) return i;
          }
          return 0;
        })();
        await executeCmd(new MoveToTimeCommand(clipId, newTimeSec, undefined, prevTime, prevTrack));
      },
      onTrimLeftEnd: async (clipId: string, newInSec: number) => {
        const clip = useProjectStore.getState().findClip(clipId);
        if (!clip) return;
        const prevIn = parseTc(clip.in);
        const prevOut = parseTc(clip.out);
        await executeCmd(new TrimCommand(clipId, newInSec, undefined, prevIn, prevOut));
      },
      onTrimRightEnd: async (clipId: string, newOutSec: number) => {
        const clip = useProjectStore.getState().findClip(clipId);
        if (!clip) return;
        const prevIn = parseTc(clip.in);
        const prevOut = parseTc(clip.out);
        await executeCmd(new TrimCommand(clipId, undefined, newOutSec, prevIn, prevOut));
      },
    }),
    [pxPerSec, snapPoints, executeCmd],
  );

  const { onPointerDown, onPointerMove, onPointerUp } =
    useDrag(dragCallbacks);

  const handleTrim = useCallback(
    async (clipId: string, inPoint: number, outPoint: number) => {
      const clip = useProjectStore.getState().findClip(clipId);
      if (!clip) return;
      const prevIn = parseTc(clip.in);
      const prevOut = parseTc(clip.out);
      await executeCmd(new TrimCommand(clipId, inPoint, outPoint, prevIn, prevOut));
    },
    [executeCmd],
  );

  const handleRemove = useCallback(
    async (clipId: string) => {
      const clip = useProjectStore.getState().findClip(clipId);
      if (!clip) return;
      const trackIdx = (() => {
        const timeline = useProjectStore.getState().timeline;
        if (!timeline) return 0;
        for (let i = 0; i < timeline.tracks.length; i++) {
          if (timeline.tracks[i].clips.some((c) => c.clip_id === clipId)) return i;
        }
        return 0;
      })();
      const inPt = parseTc(clip.in);
      const outPt = parseTc(clip.out);
      selectClip(null);
      await executeCmd(new RemoveCommand(clipId, clip.resource, trackIdx, inPt, outPt));
    },
    [executeCmd, selectClip],
  );

  // Find selected clip info
  const selectedClip: ClipInfo | null = useMemo(() => {
    if (!timeline || !selectedClipId) return null;
    for (const track of timeline.tracks) {
      const found = track.clips.find((c) => c.clip_id === selectedClipId);
      if (found) return found;
    }
    return null;
  }, [timeline, selectedClipId]);

  const clipCount = timeline
    ? timeline.tracks.reduce((sum, t) => sum + t.clips.length, 0)
    : 0;

  return (
    <AuthGuard>
      <div className="flex h-screen flex-col bg-surface-0">
        {/* Header */}
        <header
          className="sticky top-0 z-40 flex h-12 items-center justify-between border-b border-white/5 px-4"
          style={{
            background: "rgba(10, 10, 14, 0.85)",
            backdropFilter: "blur(12px)",
          }}
        >
          <div className="flex items-center gap-3">
            <span className="text-sm font-medium text-white/80">
              {projectName ?? "MLT Timeline Editor"}
            </span>
            <ProjectSelector
              currentId={projectId}
              onSelect={handleProjectSelect}
            />
          </div>

          <div className="flex items-center gap-2">
            {/* Zoom controls */}
            <div className="flex items-center gap-1">
              <button
                onClick={() => zoom(-1)}
                className="flex h-7 w-7 items-center justify-center rounded border border-white/10 bg-surface-2 text-sm text-white/60"
              >
                -
              </button>
              <span className="min-w-[36px] text-center text-xs text-white/50">
                {pxPerSec}x
              </span>
              <button
                onClick={() => zoom(1)}
                className="flex h-7 w-7 items-center justify-center rounded border border-white/10 bg-surface-2 text-sm text-white/60"
              >
                +
              </button>
            </div>

            {projectId && (
              <button
                onClick={save}
                disabled={saving}
                className="rounded border border-white/10 bg-surface-2 px-3 py-1 text-xs text-white/60 hover:text-white/80 disabled:opacity-50"
              >
                {saving ? "儲存中..." : "儲存"}
              </button>
            )}
          </div>
        </header>

        {/* Video Player */}
        <VideoPlayer videoRef={videoRef} currentTime={currentTime} />

        {/* Legend */}
        <div className="flex gap-4 border-b border-white/5 bg-surface-1 px-4 py-1.5 text-xs text-white/50">
          <span className="flex items-center gap-1.5">
            <span
              className="inline-block h-3 w-3 rounded-sm"
              style={{ background: "rgba(76,175,80,0.8)" }}
            />
            Images
          </span>
          <span className="flex items-center gap-1.5">
            <span
              className="inline-block h-3 w-3 rounded-sm"
              style={{ background: "rgba(33,150,243,0.8)" }}
            />
            Cards
          </span>
          <span className="flex items-center gap-1.5">
            <span
              className="inline-block h-0.5 w-3"
              style={{ background: "#e2b714" }}
            />
            Playhead
          </span>
        </div>

        {/* Timeline */}
        {loading && (
          <div className="flex flex-1 items-center justify-center">
            <span className="text-xs text-white/30">載入中...</span>
          </div>
        )}
        {error && (
          <div className="flex flex-1 items-center justify-center">
            <span className="text-xs text-red-400">{error}</span>
          </div>
        )}
        {timeline && !loading && (
          <div className="flex-1 overflow-hidden">
            <Timeline
              timeline={timeline}
              pxPerSec={pxPerSec}
              currentTime={currentTime}
              totalDuration={duration}
              selectedClipId={selectedClipId}
              projectId={projectId}
              onSelectClip={(id, event) => {
                if (event?.shiftKey) {
                  useEditorStore.getState().toggleClipSelection(id);
                } else {
                  selectClip(id);
                }
              }}
              onDragStart={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onRulerClick={seekTo}
            />
          </div>
        )}
        {!timeline && !loading && !error && (
          <div className="flex flex-1 items-center justify-center">
            <span className="text-xs text-white/20">
              選擇或建立一個專案
            </span>
          </div>
        )}

        {/* Properties Panel */}
        <PropertiesPanel
          clip={selectedClip}
          projectId={projectId}
          onTrim={handleTrim}
          onRemove={handleRemove}
          onSeek={seekTo}
        />

        {/* Status Bar */}
        <div className="flex justify-between border-t border-white/5 bg-surface-1 px-4 py-1.5 text-[11px] text-white/30">
          <span>{clipCount} clips</span>
          <span>
            {duration > 0
              ? `${Math.floor(duration / 60)}:${String(Math.floor(duration % 60)).padStart(2, "0")}`
              : "--:--"}
          </span>
        </div>
      </div>
    </AuthGuard>
  );
}
