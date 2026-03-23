import { useState, useCallback } from "react";
import { api } from "../api";
import { useProjectStore } from "../stores/projectStore";

interface Props {
  open: boolean;
  onClose: () => void;
}

export function ExportDialog({ open, onClose }: Props) {
  const [exporting, setExporting] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const projectId = useProjectStore((s) => s.projectId);

  const handleExport = useCallback(
    async (preset: "draft" | "resolve" | "final") => {
      if (!projectId) return;
      setExporting(true);
      setResult(null);
      try {
        const configs = {
          draft: { vcodec: "libx264", preset: "ultrafast", crf: 23 },
          resolve: { vcodec: "prores_ks", preset: "3", crf: 0 },  // ProRes 422 HQ
          final: { vcodec: "libx264", preset: "medium", crf: 18 },
        };
        const cfg = configs[preset];
        const ext = preset === "resolve" ? "mov" : "mp4";
        const res = await api.render(projectId, {
          output_path: `~/workshop/outputs/video-edit/exports/${projectId}_${preset}.${ext}`,
          ...cfg,
        }) as { path: string };
        setResult(res.path);
      } catch (err) {
        setResult(`Error: ${err}`);
      } finally {
        setExporting(false);
      }
    },
    [projectId],
  );

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div
        className="w-80 rounded-lg border border-white/10 bg-surface-0 p-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="mb-3 text-sm font-medium text-white/80">匯出影片</h3>

        <div className="flex flex-col gap-2">
          <button
            onClick={() => handleExport("draft")}
            disabled={exporting}
            className="rounded border border-white/10 bg-surface-2 px-3 py-2 text-left text-xs text-white/70 hover:bg-white/10 disabled:opacity-50"
          >
            <div className="font-medium">快速草稿</div>
            <div className="text-white/40">H.264 ultrafast -- 檢查用</div>
          </button>

          <button
            onClick={() => handleExport("resolve")}
            disabled={exporting}
            className="rounded border border-gold/30 bg-surface-2 px-3 py-2 text-left text-xs text-white/70 hover:bg-gold/10 disabled:opacity-50"
          >
            <div className="font-medium text-gold/80">DaVinci Resolve 交接</div>
            <div className="text-white/40">ProRes 422 HQ -- 調色/特效用</div>
          </button>

          <button
            onClick={() => handleExport("final")}
            disabled={exporting}
            className="rounded border border-white/10 bg-surface-2 px-3 py-2 text-left text-xs text-white/70 hover:bg-white/10 disabled:opacity-50"
          >
            <div className="font-medium">最終輸出</div>
            <div className="text-white/40">H.264 medium CRF 18 -- 交付用</div>
          </button>
        </div>

        {exporting && (
          <div className="mt-3 text-center text-xs text-white/40">渲染中...</div>
        )}
        {result && (
          <div className="mt-3 rounded bg-surface-2 p-2 text-[10px] text-white/50 break-all">
            {result}
          </div>
        )}

        <button
          onClick={onClose}
          className="mt-3 w-full rounded border border-white/10 py-1 text-xs text-white/40 hover:text-white/60"
        >
          關閉
        </button>
      </div>
    </div>
  );
}
