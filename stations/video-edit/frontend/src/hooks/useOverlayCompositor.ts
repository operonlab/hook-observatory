import { useEffect, useRef, useCallback } from "react";
import type { TimelineInfo } from "../types";
import { parseTc } from "../utils";

/** Map MLT filter types to Canvas filter CSS strings. */
function mltFilterToCss(filterType: string, params: Record<string, string>): string | null {
  switch (filterType) {
    case "brightness":
      return `brightness(${params.level ?? "1"})`;
    case "greyscale":
    case "grayscale":
      return "grayscale(1)";
    case "blur:gaussian":
    case "blur":
      return `blur(${params.radius ?? "2"}px)`;
    case "avfilter.eq": {
      const parts: string[] = [];
      if (params.brightness) parts.push(`brightness(${1 + parseFloat(params.brightness)})`);
      if (params.contrast) parts.push(`contrast(${params.contrast})`);
      if (params.saturation) parts.push(`saturate(${params.saturation})`);
      return parts.length > 0 ? parts.join(" ") : null;
    }
    default:
      return null;
  }
}

type LayerType = "video" | "image" | "text";

interface OverlayClip {
  clipId: string;
  trackIndex: number;
  layerType: LayerType;
  timelineStart: number;
  timelineEnd: number;
  // Image overlay
  img?: HTMLImageElement;
  imgLoaded?: boolean;
  // Text overlay (pango)
  text?: string;
  fontSize?: number;
  color?: string;
  // Compositing
  opacity: number;
  filters: { type: string; params: Record<string, string> }[];
}

interface UseOverlayCompositorOpts {
  timeline: TimelineInfo | null;
  projectId: string | null;
  videoRef: React.RefObject<HTMLVideoElement | null>;
  canvasRef: React.RefObject<HTMLCanvasElement | null>;
  basePath: string;
  /** Active filters on the main video track (track 0) */
  videoFilters?: { type: string; params: Record<string, string> }[];
}

export function useOverlayCompositor({
  timeline,
  projectId,
  videoRef,
  canvasRef,
  basePath,
  videoFilters,
}: UseOverlayCompositorOpts) {
  const overlaysRef = useRef<OverlayClip[]>([]);
  const rafRef = useRef<number>(0);

  // Build overlay list from timeline tracks 1+
  useEffect(() => {
    overlaysRef.current = [];
    if (!timeline || !projectId) return;

    for (let i = 1; i < timeline.tracks.length; i++) {
      const track = timeline.tracks[i];
      for (const clip of track.clips) {
        const resource = clip.resource || "";
        const isText = resource === "" || resource.includes("pango");
        const isImage = /\.(png|jpe?g|gif|webp|svg)$/i.test(resource);

        const ov: OverlayClip = {
          clipId: clip.clip_id,
          trackIndex: i,
          layerType: isText ? "text" : isImage ? "image" : "video",
          timelineStart: parseTc(clip.timeline_start),
          timelineEnd: parseTc(clip.timeline_end),
          opacity: 1.0,
          filters: [],
        };

        if (ov.layerType === "image") {
          const img = new Image();
          img.crossOrigin = "anonymous";
          ov.img = img;
          ov.imgLoaded = false;
          img.onload = () => { ov.imgLoaded = true; };
          img.src = `${basePath}/projects/${projectId}/clips/${clip.clip_id}/thumbnail`;
        }

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

    // --- Layer 0: Main video with CSS filter mapping ---
    ctx.save();
    if (videoFilters && videoFilters.length > 0) {
      const cssFilters = videoFilters
        .map((f) => mltFilterToCss(f.type, f.params))
        .filter(Boolean)
        .join(" ");
      if (cssFilters) {
        ctx.filter = cssFilters;
      }
    }
    ctx.drawImage(mainVideo, 0, 0, vw, vh);
    ctx.restore();

    // --- Layers 1+: Overlay tracks ---
    const t = mainVideo.currentTime;
    for (const ov of overlaysRef.current) {
      if (t < ov.timelineStart || t > ov.timelineEnd) continue;

      ctx.save();
      ctx.globalAlpha = ov.opacity;

      // Apply per-clip CSS filters
      if (ov.filters.length > 0) {
        const css = ov.filters
          .map((f) => mltFilterToCss(f.type, f.params))
          .filter(Boolean)
          .join(" ");
        if (css) ctx.filter = css;
      }

      if (ov.layerType === "image" && ov.img && ov.imgLoaded) {
        ctx.drawImage(ov.img, 0, 0, vw, vh);
      } else if (ov.layerType === "text" && ov.text) {
        const fontSize = ov.fontSize ?? 48;
        ctx.font = `${fontSize}px sans-serif`;
        ctx.fillStyle = ov.color ?? "#ffffff";
        ctx.textAlign = "center";
        ctx.textBaseline = "bottom";
        ctx.fillText(ov.text, vw / 2, vh - 40);
      }

      ctx.restore();
    }
  }, [videoRef, canvasRef, videoFilters]);

  // RAF loop
  const renderLoop = useCallback(() => {
    drawComposite();
    rafRef.current = requestAnimationFrame(renderLoop);
  }, [drawComposite]);

  useEffect(() => {
    rafRef.current = requestAnimationFrame(renderLoop);
    return () => cancelAnimationFrame(rafRef.current);
  }, [renderLoop]);

  // Sync with video events
  useEffect(() => {
    const mainVideo = videoRef.current;
    if (!mainVideo) return;

    const onSeeked = () => drawComposite();
    const onPause = () => drawComposite();

    mainVideo.addEventListener("seeked", onSeeked);
    mainVideo.addEventListener("pause", onPause);
    return () => {
      mainVideo.removeEventListener("seeked", onSeeked);
      mainVideo.removeEventListener("pause", onPause);
    };
  }, [videoRef, drawComposite]);
}
