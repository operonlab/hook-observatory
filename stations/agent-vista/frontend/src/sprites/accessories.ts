// Accessory overlay system (C5) — deterministic per-session accessories
// Draws small pixel overlays on top of character sprites

export interface Accessory {
  id: string;
  label: string;
  /** Pixel pattern (color strings, '' = transparent) */
  pattern: string[][];
  /** Offset from character top-left (in sprite pixels, before zoom) */
  offsetX: number;
  offsetY: number;
}

// ── Accessory definitions (10px wide character frame) ──────────────────

const HAT: Accessory = {
  id: 'hat', label: '帽子',
  pattern: [
    ['', '', '#C04020', '#C04020', '#C04020', '#C04020', '#C04020', '', '', ''],
    ['', '#C04020', '#E05030', '#E05030', '#E05030', '#E05030', '#E05030', '#C04020', '', ''],
    ['#8A2010', '#C04020', '#C04020', '#C04020', '#C04020', '#C04020', '#C04020', '#C04020', '#8A2010', ''],
  ],
  offsetX: 0, offsetY: -2,
};

const GLASSES: Accessory = {
  id: 'glasses', label: '眼鏡',
  pattern: [
    ['', '#333', '#555', '#555', '#333', '#333', '#555', '#555', '#333', ''],
    ['', '#333', '#89C4E8', '#89C4E8', '#333', '#333', '#89C4E8', '#89C4E8', '#333', ''],
  ],
  offsetX: 0, offsetY: 3,
};

const HEADPHONES: Accessory = {
  id: 'headphones', label: '耳機',
  pattern: [
    ['', '', '', '#444', '#444', '#444', '#444', '', '', ''],
    ['', '', '#444', '', '', '', '', '#444', '', ''],
    ['', '#666', '', '', '', '', '', '', '#666', ''],
    ['', '#888', '', '', '', '', '', '', '#888', ''],
  ],
  offsetX: 0, offsetY: -1,
};

const BOWTIE: Accessory = {
  id: 'bowtie', label: '領結',
  pattern: [
    ['', '', '', '#D02050', '#FFD700', '#FFD700', '#D02050', '', '', ''],
    ['', '', '', '', '#D02050', '#D02050', '', '', '', ''],
  ],
  offsetX: 0, offsetY: 7,
};

const ANTENNA: Accessory = {
  id: 'antenna', label: '天線',
  pattern: [
    ['', '', '', '', '#00FF88', '', '', '', '', ''],
    ['', '', '', '', '#44AA66', '', '', '', '', ''],
    ['', '', '', '', '#44AA66', '', '', '', '', ''],
  ],
  offsetX: 0, offsetY: -3,
};

const CROWN: Accessory = {
  id: 'crown', label: '皇冠',
  pattern: [
    ['', '', '#FFD700', '', '#FFD700', '#FFD700', '', '#FFD700', '', ''],
    ['', '', '#FFD700', '#FFD700', '#FFD700', '#FFD700', '#FFD700', '#FFD700', '', ''],
    ['', '', '#DAA520', '#DAA520', '#DAA520', '#DAA520', '#DAA520', '#DAA520', '', ''],
  ],
  offsetX: 0, offsetY: -2,
};

const SCARF: Accessory = {
  id: 'scarf', label: '圍巾',
  pattern: [
    ['', '', '#2266CC', '#2266CC', '#DD3333', '#DD3333', '#2266CC', '#2266CC', '', ''],
    ['', '', '', '#2266CC', '#DD3333', '#DD3333', '#2266CC', '', '', ''],
    ['', '', '', '', '#DD3333', '#DD3333', '', '', '', ''],
  ],
  offsetX: 0, offsetY: 6,
};

/** All available accessories (null = no accessory) */
export const ACCESSORIES: (Accessory | null)[] = [
  null,       // ~30% chance of no accessory
  null,
  null,
  HAT,
  GLASSES,
  HEADPHONES,
  BOWTIE,
  ANTENNA,
  CROWN,
  SCARF,
];

/** Deterministic accessory selection based on session/agent ID */
export function getAccessory(sessionId: string): Accessory | null {
  let hash = 0;
  for (let i = 0; i < sessionId.length; i++) {
    hash = ((hash << 5) - hash + sessionId.charCodeAt(i)) | 0;
  }
  const idx = Math.abs(hash) % ACCESSORIES.length;
  return ACCESSORIES[idx];
}

/** Draw an accessory overlay on top of a character sprite */
export function drawAccessory(
  ctx: CanvasRenderingContext2D,
  accessory: Accessory,
  charScreenX: number,
  charScreenY: number,
  zoom: number,
) {
  const px = zoom; // each sprite pixel = zoom screen pixels
  for (let row = 0; row < accessory.pattern.length; row++) {
    for (let col = 0; col < accessory.pattern[row].length; col++) {
      const color = accessory.pattern[row][col];
      if (!color) continue;
      const sx = charScreenX + (accessory.offsetX + col) * px;
      const sy = charScreenY + (accessory.offsetY + row) * px;
      ctx.fillStyle = color;
      ctx.fillRect(sx, sy, px, px);
    }
  }
}
