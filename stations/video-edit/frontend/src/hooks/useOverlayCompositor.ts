import { useEffect, useRef, useCallback } from "react";
import type { TimelineInfo } from "../types";
import { parseTc } from "../utils";

interface OverlayClip {
  clipId: string;
  trackIndex: number;
  timelineStart: number;
  timelineEnd: number;
  img: HTMLImageElement;
  loaded: boolean;
}

interface UseOverlayCompositorOpts {
  timeline: TimelineInfo | null;
  projectId: string | null;
  videoRef: React.RefObject<HTMLVideoElement | null>;
  canvasRef: React.RefObject<HTMLCanvasElement | null>;
  basePath: string;
}

export function useOverlayCompositor({
  timeline,
  projectId,
  videoRef,
  canvasRef,
  basePath,
}: UseOverlayCompositorOpts) {
  const overlaysRef = useRef<OverlayClip[]>([]);
  const rafRef = useRef<number>(0);
  const isPlayingRef = useRef(false);

  // Build overlay list — load static PNG thumbnails (alpha-preserved)
  useEffect(() => {
    overlaysRef.current = [];

    if (!timeline || !projectId) return;

    for (let i = 1; i < timeline.tracks.length; i++) {
      const track = timeline.tracks[i];
      for (const clip of track.clips) {
        const img = new Image();
        img.crossOrigin = "anonymous";

        const ov: OverlayClip = {
          clipId: clip.clip_id,
          trackIndex: i,
          timelineStart: parseTc(clip.timeline_start),
          timelineEnd: parseTc(clip.timeline_end),
          img,
          loaded: false,
        };

        img.onload = () => { ov.loaded = true; };
        img.src = `${basePath}/projects/${projectId}/clips/${clip.clip_id}/thumbnail`;

        overlaysRef.current.push(ov);
      }
    }
  }, [timeline, projectId, basePath]);

  // Draw composite frame
  const drawComposite = useCallback(() => {
    const mainVideo = videoRef.current;
    const canvas = canvasRef.current;
    if (!mainVideo || !canvas || mainVideo.readyState < 2) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const vw = mainVideo.videoWidth || 1920;
    const vh = mainVideo.videoHeight || 1080;
    if (canvas.width !== vw || canvas.height !== vh) {
      canvas.width = vw;
      canvas.height = vh;
    }

    // Draw main video
    ctx.drawImage(mainVideo, 0, 0, vw, vh);

    // Draw active overlay images on top (full opacity — this is the intended compositing)
    const t = mainVideo.currentTime;
    for (const ov of overlaysRef.current) {
      if (!ov.loaded) continue;
      if (t < ov.timelineStart || t > ov.timelineEnd) continue;
      ctx.drawImage(ov.img, 0, 0, vw, vh);
    }
  }, [videoRef, canvasRef]);

  // RAF loop — always draw (paused frames are cheap, same image repeated)
  const renderLoop = useCallback(() => {
    drawComposite();
    rafRef.current = requestAnimationFrame(renderLoop);
  }, [drawComposite]);

  useEffect(() => {
    rafRef.current = requestAnimationFrame(renderLoop);
    return () => cancelAnimationFrame(rafRef.current);
  }, [renderLoop]);

  // Sync with main video events
  useEffect(() => {
    const mainVideo = videoRef.current;
    if (!mainVideo) return;

    const onPlay = () => {
      isPlayingRef.current = true;
    };

    const onPause = () => {
      isPlayingRef.current = false;
      // Draw one more frame to show paused state with overlays
      drawComposite();
    };

    const onSeeked = () => {
      drawComposite();
    };

    mainVideo.addEventListener("play", onPlay);
    mainVideo.addEventListener("pause", onPause);
    mainVideo.addEventListener("seeked", onSeeked);
    return () => {
      mainVideo.removeEventListener("play", onPlay);
      mainVideo.removeEventListener("pause", onPause);
      mainVideo.removeEventListener("seeked", onSeeked);
    };
  }, [videoRef, drawComposite]);
}
