import { useEffect, useState } from "react";
import { api } from "../api";
import type { Project, ProjectInfo } from "../types";

interface Props {
  currentId: string | null;
  onSelect: (project: ProjectInfo) => void;
}

export function ProjectSelector({ currentId, onSelect }: Props) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [showNew, setShowNew] = useState(false);
  const [newName, setNewName] = useState("");

  useEffect(() => {
    api.listProjects().then(setProjects).catch(console.error);
  }, []);

  const handleSelect = async (e: React.ChangeEvent<HTMLSelectElement>) => {
    const path = e.target.value;
    if (!path) return;
    try {
      const info = await api.openProject(path);
      onSelect(info);
    } catch (err) {
      console.error("Failed to open project:", err);
    }
  };

  const handleCreate = async () => {
    if (!newName.trim()) return;
    try {
      const info = await api.createProject({ name: newName.trim() });
      onSelect(info);
      setShowNew(false);
      setNewName("");
      api.listProjects().then(setProjects);
    } catch (err) {
      console.error("Failed to create project:", err);
    }
  };

  return (
    <div className="flex items-center gap-2">
      <select
        className="rounded border border-white/10 bg-surface-2 px-2 py-1 text-xs text-white/80"
        value={currentId ?? ""}
        onChange={handleSelect}
      >
        <option value="">-- 選擇專案 --</option>
        {projects.map((p) => (
          <option key={p.path} value={p.path}>
            {p.name}
          </option>
        ))}
      </select>

      {showNew ? (
        <div className="flex items-center gap-1">
          <input
            className="rounded border border-white/10 bg-surface-2 px-2 py-1 text-xs text-white"
            placeholder="專案名稱"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleCreate()}
            autoFocus
          />
          <button
            onClick={handleCreate}
            className="rounded bg-accent/20 px-2 py-1 text-xs text-accent"
          >
            建立
          </button>
          <button
            onClick={() => setShowNew(false)}
            className="px-1 text-xs text-white/40"
          >
            ✕
          </button>
        </div>
      ) : (
        <button
          onClick={() => setShowNew(true)}
          className="rounded border border-white/10 bg-surface-2 px-2 py-1 text-xs text-white/60 hover:text-white/80"
        >
          + 新建
        </button>
      )}
    </div>
  );
}
