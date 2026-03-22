interface Props {
  currentTime: number;
  pxPerSec: number;
  labelOffset: number;
  height: number;
}

export function Playhead({ currentTime, pxPerSec, labelOffset, height }: Props) {
  const left = labelOffset + currentTime * pxPerSec;

  return (
    <div
      className="pointer-events-none absolute top-0 z-50"
      style={{
        left: `${left}px`,
        width: "2px",
        height: `${height}px`,
        background: "#e2b714",
      }}
    >
      <div
        style={{
          position: "absolute",
          top: 0,
          left: "-5px",
          width: 0,
          height: 0,
          borderLeft: "6px solid transparent",
          borderRight: "6px solid transparent",
          borderTop: "8px solid #e2b714",
        }}
      />
    </div>
  );
}
