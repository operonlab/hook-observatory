import type { KASProfile } from "@/types";

interface ProfileWidgetProps {
  profile: KASProfile | null;
  loading?: boolean;
}

interface DimensionBarProps {
  label: string;
  shortLabel: string;
  score: number;
  color: string;
}

function DimensionBar({ label, shortLabel, score, color }: DimensionBarProps) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between">
        <span className="text-sm" style={{ color: "var(--subtext1)" }}>
          {label}
          <span className="ml-1 text-xs" style={{ color: "var(--subtext0)" }}>
            ({shortLabel})
          </span>
        </span>
        <span className="text-sm font-semibold" style={{ color }}>
          {score}
        </span>
      </div>
      <div
        className="h-1.5 w-full rounded-full overflow-hidden"
        style={{ backgroundColor: "var(--surface0)" }}
      >
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{
            width: `${Math.min(score, 100)}%`,
            backgroundColor: color,
          }}
        />
      </div>
    </div>
  );
}

function SkeletonBar() {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between">
        <div
          className="h-4 w-24 rounded animate-pulse"
          style={{ backgroundColor: "var(--surface0)" }}
        />
        <div
          className="h-4 w-8 rounded animate-pulse"
          style={{ backgroundColor: "var(--surface0)" }}
        />
      </div>
      <div
        className="h-1.5 w-full rounded-full animate-pulse"
        style={{ backgroundColor: "var(--surface0)" }}
      />
    </div>
  );
}

export default function ProfileWidget({ profile, loading = false }: ProfileWidgetProps) {
  return (
    <div
      className="rounded-xl border p-5"
      style={{ backgroundColor: "var(--mantle)", borderColor: "var(--surface0)" }}
    >
      <h2 className="font-semibold mb-4" style={{ color: "var(--text)" }}>
        KAS 能力圖譜
      </h2>

      {loading ? (
        <div className="flex flex-col gap-4">
          <SkeletonBar />
          <SkeletonBar />
          <SkeletonBar />
        </div>
      ) : profile === null ? (
        <p className="text-sm" style={{ color: "var(--subtext0)" }}>
          尚未建立 Profile
        </p>
      ) : (
        <div className="flex flex-col gap-4">
          <DimensionBar
            label="知識"
            shortLabel="K"
            score={profile.knowledge_score}
            color="var(--blue)"
          />
          <DimensionBar
            label="態度"
            shortLabel="A"
            score={profile.attitude_score}
            color="var(--mauve)"
          />
          <DimensionBar
            label="技能"
            shortLabel="S"
            score={profile.skill_score}
            color="var(--green)"
          />
        </div>
      )}
    </div>
  );
}
