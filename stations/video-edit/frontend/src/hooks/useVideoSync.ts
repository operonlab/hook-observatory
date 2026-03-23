import { useRef, useCallback, useEffect, useState } from "react";

export function useVideoSync() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

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
  }, []);

  const seekTo = useCallback((t: number) => {
    if (videoRef.current) {
      videoRef.current.currentTime = t;
      setCurrentTime(t);
    }
  }, []);

  return { videoRef, currentTime, duration, seekTo };
}
