export type BlockType = "knowledge" | "skill" | "attitude" | "general";

export type ViewMode = "grid" | "list";

export type SortField = "created_at" | "updated_at" | "confidence";
export type SortOrder = "asc" | "desc";

export interface BlockFilters {
  blockType: BlockType | null;
  tag: string | null;
  sortField: SortField;
  sortOrder: SortOrder;
}

export interface GalaxyNode {
  id: string;
  label: string;
  type: BlockType;
  confidence: number;
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
}

export interface GalaxyLink {
  source: string;
  target: string;
  strength: number;
}

export const BLOCK_TYPE_CONFIG: Record<BlockType, { label: string; color: string }> = {
  knowledge: { label: "知識", color: "var(--blue)" },
  skill: { label: "技能", color: "var(--green)" },
  attitude: { label: "態度", color: "var(--mauve)" },
  general: { label: "通用", color: "var(--text)" },
};
