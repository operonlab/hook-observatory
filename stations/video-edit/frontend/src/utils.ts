/** Convert seconds to HH:MM:SS.mmm timecode. */
export function formatTc(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  const ms = Math.round((s % 1) * 1000);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}.${String(ms).padStart(3, "0")}`;
}

/** Parse HH:MM:SS.mmm timecode to seconds. */
export function parseTc(tc: string): number {
  const parts = tc.split(":");
  if (parts.length === 3) {
    return (
      parseInt(parts[0]) * 3600 +
      parseInt(parts[1]) * 60 +
      parseFloat(parts[2])
    );
  }
  if (parts.length === 2) {
    return parseInt(parts[0]) * 60 + parseFloat(parts[1]);
  }
  return parseFloat(tc) || 0;
}

/** Extract friendly filename from a full path. */
export function friendlyName(resource: string): string {
  const parts = resource.split("/");
  return (parts[parts.length - 1] || resource).replace(
    /\.(mov|png|mp4|jpg|jpeg|webm|mlt)$/i,
    "",
  );
}

/** Track index → color class info. */
export function trackColor(trackIndex: number): {
  bg: string;
  border: string;
  label: string;
} {
  const colors = [
    { bg: "rgba(100,100,100,0.4)", border: "rgba(100,100,100,0.6)", label: "Video" },
    { bg: "rgba(76,175,80,0.6)", border: "rgba(76,175,80,0.8)", label: "Images" },
    { bg: "rgba(33,150,243,0.6)", border: "rgba(33,150,243,0.8)", label: "Cards" },
    { bg: "rgba(255,152,0,0.6)", border: "rgba(255,152,0,0.8)", label: "Audio" },
    { bg: "rgba(156,39,176,0.6)", border: "rgba(156,39,176,0.8)", label: "FX" },
  ];
  return colors[trackIndex] || colors[0];
}
