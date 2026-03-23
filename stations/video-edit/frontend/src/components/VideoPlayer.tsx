import { useCallback } from "react";
import { formatTc } from "../utils";

interface Props {
  videoRef: React.RefObject<HTMLVideoElement | null>;
  canvasRef: React.RefObject<HTMLCanvasElement | null>;
  currentTime: number;
  hasSrc: boolean;
}

export function VideoPlayer({ videoRef, canvasRef, currentTime, hasSrc }: Props) {
  const handleError = useCallback((e: React.SyntheticEvent<HTMLVideoElement>) => {
    const video = e.currentTarget;
    if (video.error?.code === MediaError.MEDIA_ERR_ABORTED) {
      e.preventDefault();
    }
  }, []);

  const togglePlay = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) video.play().catch(() => {});
    else video.pause();
  }, [videoRef]);

  return (
    <div className="relative bg-black">
      {/* Video element — off-screen but NOT display:none (Firefox won't decode hidden videos) */}
      <video
        ref={videoRef}
        style={{
          position: "absolute",
          width: "1px",
          height: "1px",
          opacity: 0,
          pointerEvents: "none",
          zIndex: -1,
        }}
        controls={false}
        preload="auto"
        playsInline
        onError={handleError}
      />

      {/* Canvas — maintains aspect ratio via CSS aspect-ratio */}
      {hasSrc ? (
        <div className="flex items-center justify-center" style={{ maxHeight: "40vh" }}>
          <canvas
            ref={canvasRef}
            className="block max-w-full cursor-pointer"
            style={{
              maxHeight: "40vh",
              aspectRatio: "16 / 9",
              objectFit: "contain",
            }}
            onClick={togglePlay}
          />
        </div>
      ) : (
        <div className="flex h-32 items-center justify-center">
          <span className="text-xs text-white/20">選擇專案後顯示預覽</span>
        </div>
      )}

      {hasSrc && (
        <div className="absolute bottom-0 left-0 right-0 flex items-center gap-2 bg-gradient-to-t from-black/60 to-transparent px-3 py-2">
          <button
            className="text-xs text-white/80 hover:text-white"
            onClick={togglePlay}
          >
            ▶/⏸
          </button>
          <span className="text-xs tabular-nums text-white/60">
            {formatTc(currentTime)}
          </span>
        </div>
      )}
    </div>
  );
}
