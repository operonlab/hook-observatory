import { useRef, useCallback, useEffect, useState } from "react";

export function useVideoSync(src?: string) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  // Manage src changes safely
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    if (src) {
      // Only update if src actually changed
      const currentSrc = video.getAttribute("src") || "";
      if (currentSrc !== src) {
        video.pause();
        video.setAttribute("src", src);
        // Catch the play promise rejection that happens when load() interrupts
        video.load();
      }
    } else {
      // No src — just pause, do NOT call load() on empty src
      video.pause();
    }
  }, [src]);

  // Attach media event listeners
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const onMeta = () => setDuration(video.duration || 0);
    video.addEventListener("loadedmetadata", onMeta);

    // Use requestVideoFrameCallback for frame-accurate sync if available
    let rVFCHandle: number | undefined;
    if ("requestVideoFrameCallback" in HTMLVideoElement.prototype) {
      const onVideoFrame = (_now: DOMHighResTimeStamp, _meta: VideoFrameCallbackMetadata) => {
        setCurrentTime(video.currentTime);
        rVFCHandle = video.requestVideoFrameCallback(onVideoFrame);
      };
      rVFCHandle = video.requestVideoFrameCallback(onVideoFrame);
    } else {
      // Fallback: timeupdate (~4Hz)
      const onTimeUpdate = () => setCurrentTime(video.currentTime);
      video.addEventListener("timeupdate", onTimeUpdate);
      return () => {
        video.removeEventListener("timeupdate", onTimeUpdate);
        video.removeEventListener("loadedmetadata", onMeta);
      };
    }

    return () => {
      if (rVFCHandle !== undefined) {
        video.cancelVideoFrameCallback(rVFCHandle);
      }
      video.removeEventListener("loadedmetadata", onMeta);
    };
    // Re-run when src changes because the video element's event state resets on load
  }, [src]);

  const seekTo = useCallback((t: number) => {
    const video = videoRef.current;
    if (video && video.readyState >= 1) {
      video.currentTime = t;
      setCurrentTime(t);
    }
  }, []);

  return { videoRef, currentTime, duration, seekTo };
}
