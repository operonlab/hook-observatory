import type { KASProfile } from "@/types";
import { useMemvaultStore } from "../stores";
import InfoTip from "./InfoTip";

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

function KgStatsRow({ label, count, color }: { label: string; count: number; color: string }) {
  return (
    <div className="flex items-center justify-between text-xs">
      <div className="flex items-center gap-1.5">
        <span
          className="inline-block h-2 w-2 rounded-full shrink-0"
          style={{ backgroundColor: color }}
        />
        <span style={{ color: "var(--subtext1)" }}>{label}</span>
      </div>
      <span className="font-medium" style={{ color }}>{count}</span>
    </div>
  );
}

export default function ProfileWidget({ profile, loading = false }: ProfileWidgetProps) {
  const { kg_wisdom, kg_clusters, kg_triples, kg_triplesTotal, kg_attitudes, recalculateProfile } =
    useMemvaultStore();

  const hasKgData =
    kg_wisdom.length > 0 ||
    kg_clusters.length > 0 ||
    kg_triplesTotal > 0 ||
    kg_attitudes.length > 0;

  return (
    <div
      className="rounded-xl border p-4 sm:p-5"
      style={{ backgroundColor: "var(--mantle)", borderColor: "var(--surface0)" }}
    >
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-1.5">
          <h2 className="text-sm font-semibold" style={{ color: "var(--text)" }}>
            KAS 能力圖譜
          </h2>
          <InfoTip text={"KAS 分數以對數尺度計算，滿分 100：\n\nK（知識）= 三元組數量基礎分（100個≈50, 2000個≈70）+ 群集加成（每個+2, 上限15）+ 智慧結晶加成（每個+2, 上限15）\nA（態度）= 活躍態度數量基礎分（上限60）+ 平均信心度加成（上限40）\nS（技能）= 調用次數基礎分（上限50）+ 技能多樣性（每種+2, 上限25）+ 成功率加成（上限25）\n\n知識圖譜三層架構：\nL0 三元組 — 從對話萃取的「主詞→謂詞→受詞」事實\nL1 知識群集 — 語義相近三元組自動聚合成主題群\nL2 智慧結晶 — 跨群集歸納的高層洞見與策略\n\n點擊「重新計算」從最新 KG 數據刷新。"} />
        </div>
        <button
          onClick={() => recalculateProfile()}
          className="rounded-lg px-2.5 py-1.5 text-xs transition-colors"
          style={{
            backgroundColor: "var(--surface0)",
            color: "var(--subtext0)",
            minHeight: 36,
          }}
          title="從 KG 數據重新計算分數"
        >
          重新計算
        </button>
      </div>

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

      {/* KG Stats */}
      {hasKgData && (
        <div
          className="mt-4 pt-3 border-t space-y-1.5"
          style={{ borderColor: "var(--surface0)" }}
        >
          <p className="text-xs font-medium mb-2" style={{ color: "var(--subtext0)" }}>
            知識圖譜
          </p>
          {/* Mobile: 2-column grid for compact display */}
          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 sm:block sm:space-y-1.5">
            <KgStatsRow label="智慧結晶" count={kg_wisdom.length} color="var(--peach)" />
            <KgStatsRow label="知識群集" count={kg_clusters.length} color="var(--blue)" />
            <KgStatsRow label="三元組" count={kg_triplesTotal} color="var(--teal)" />
            <KgStatsRow label="態度" count={kg_attitudes.length} color="var(--mauve)" />
          </div>
        </div>
      )}
    </div>
  );
}
