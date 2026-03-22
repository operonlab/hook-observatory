import { formatTc } from "../utils";

interface Props {
  videoRef: React.RefObject<HTMLVideoElement | null>;
  currentTime: number;
}

export function VideoPlayer({ videoRef, currentTime }: Props) {
  return (
    <div className="relative bg-black">
      <video
        ref={videoRef}
        className="block w-full"
        style={{ maxHeight: "40vh" }}
        controls
        preload="metadata"
        playsInline
      />
      <div className="pointer-events-none absolute bottom-2 left-3 rounded bg-black/70 px-2.5 py-1 text-xs tabular-nums text-white">
        {formatTc(currentTime)}
      </div>
    </div>
  );
}
