import { useState, useCallback, useMemo } from "react";
import { AuthGuard } from "./components/AuthGuard";
import { ProjectSelector } from "./components/ProjectSelector";
import { VideoPlayer } from "./components/VideoPlayer";
import { Timeline } from "./components/Timeline";
import { PropertiesPanel } from "./components/PropertiesPanel";
import { useTimeline } from "./hooks/useTimeline";
import { useVideoSync } from "./hooks/useVideoSync";
import { useDrag } from "./hooks/useDrag";
import { api } from "./api";
import type { ProjectInfo, ClipInfo } from "./types";

export default function App() {
  const [projectId, setProjectId] = useState<string | null>(null);
  const [projectName, setProjectName] = useState<string | null>(null);
  const [selectedClipId, setSelectedClipId] = useState<string | null>(null);
  const [pxPerSec, setPxPerSec] = useState(6);
  const [saving, setSaving] = useState(false);

  const { timeline, loading, error, load, reload } = useTimeline();
  const { videoRef, currentTime, duration, seekTo } = useVideoSync();

  const handleProjectSelect = useCallback(
    async (info: ProjectInfo) => {
      setProjectId(info.id);
      setProjectName(info.name);
      setSelectedClipId(null);
      await load(info.id);
    },
    [load],
  );

  const handleSave = useCallback(async () => {
    if (!projectId) return;
    setSaving(true);
    try {
      await api.saveProject(projectId);
    } catch (err) {
      console.error("Save failed:", err);
    } finally {
      setSaving(false);
    }
  }, [projectId]);

  const handleZoom = useCallback(
    (delta: number) => {
      setPxPerSec((prev) => Math.max(1, Math.min(20, prev + delta)));
    },
    [],
  );

  // Drag handlers
  const dragCallbacks = useMemo(
    () => ({
      pxPerSec,
      trackHeight: 48,
      onMoveEnd: async (clipId: string, newTimeSec: number) => {
        if (!projectId) return;
        await api.moveClip(projectId, clipId, {
          new_position: Math.round(newTimeSec),
        });
        await reload(projectId);
      },
      onTrimLeftEnd: async (clipId: string, newInSec: number) => {
        if (!projectId) return;
        await api.trimClip(projectId, clipId, { in_point: newInSec });
        await reload(projectId);
      },
      onTrimRightEnd: async (clipId: string, newOutSec: number) => {
        if (!projectId) return;
        await api.trimClip(projectId, clipId, { out_point: newOutSec });
        await reload(projectId);
      },
    }),
    [pxPerSec, projectId, reload],
  );

  const { onPointerDown, onPointerMove, onPointerUp } =
    useDrag(dragCallbacks);

  // Trim from properties panel
  const handleTrim = useCallback(
    async (clipId: string, inPoint: number, outPoint: number) => {
      if (!projectId) return;
      await api.trimClip(projectId, clipId, {
        in_point: inPoint,
        out_point: outPoint,
      });
      await reload(projectId);
    },
    [projectId, reload],
  );

  const handleRemove = useCallback(
    async (clipId: string) => {
      if (!projectId) return;
      await api.removeClip(projectId, clipId);
      setSelectedClipId(null);
      await reload(projectId);
    },
    [projectId, reload],
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

  // Total clip count
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
                onClick={() => handleZoom(-1)}
                className="flex h-7 w-7 items-center justify-center rounded border border-white/10 bg-surface-2 text-sm text-white/60"
              >
                -
              </button>
              <span className="min-w-[36px] text-center text-xs text-white/50">
                {pxPerSec}x
              </span>
              <button
                onClick={() => handleZoom(1)}
                className="flex h-7 w-7 items-center justify-center rounded border border-white/10 bg-surface-2 text-sm text-white/60"
              >
                +
              </button>
            </div>

            {projectId && (
              <button
                onClick={handleSave}
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
              onSelectClip={setSelectedClipId}
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
