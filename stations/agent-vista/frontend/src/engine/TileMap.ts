// Tile grid definition + multi-room office layout
// 4 rooms connected by cross-shaped corridors:
//   Top-left:     Claude Code Studio (coding agents)
//   Top-right:    Gemini Research Lab (research agents)
//   Bottom-left:  Codex Build Lab (build/test agents)
//   Bottom-right: Rest Room (resting agents)

export const TILE = 16; // 16×16 pixel tiles

// ── Room IDs ────────────────────────────────────────────────────────────────

export type RoomId = 'claude_studio' | 'gemini_lab' | 'codex_lab' | 'rest_room' | 'corridor';

// ── Room bounds (interior walkable area, inclusive) ─────────────────────────

export interface RoomBounds {
  id: RoomId;
  x0: number; y0: number;
  x1: number; y1: number;
  label: string;
  labelEn: string;
}

export const ROOMS: RoomBounds[] = [
  { id: 'claude_studio', x0: 1,  y0: 1,  x1: 21, y1: 13, label: 'Code Studio',    labelEn: 'Claude' },
  { id: 'gemini_lab',    x0: 28, y0: 1,  x1: 48, y1: 13, label: 'Research Lab',    labelEn: 'Gemini' },
  { id: 'codex_lab',     x0: 1,  y0: 20, x1: 21, y1: 32, label: 'Build Lab',       labelEn: 'Codex' },
  { id: 'rest_room',     x0: 28, y0: 20, x1: 48, y1: 32, label: 'Break Room',      labelEn: 'Rest' },
];

/** Get room bounds by ID */
export function getRoomBounds(id: RoomId): RoomBounds | undefined {
  return ROOMS.find(r => r.id === id);
}

/** Check if a tile is inside a specific room */
export function isInRoom(x: number, y: number, room: RoomBounds): boolean {
  return x >= room.x0 && x <= room.x1 && y >= room.y0 && y <= room.y1;
}

/** Find which room a tile belongs to (null if corridor/wall) */
export function tileRoom(x: number, y: number): RoomId | null {
  for (const r of ROOMS) {
    if (isInRoom(x, y, r)) return r.id;
  }
  // Check corridors
  if (isInCorridor(x, y)) return 'corridor';
  return null;
}

// ── Corridor bounds ─────────────────────────────────────────────────────────

/** Vertical corridor: 4 tiles wide through center */
export const CORRIDOR_V = { x0: 23, y0: 1, x1: 26, y1: 32 };

/** Horizontal corridor: 4 tiles tall through middle */
export const CORRIDOR_H = { x0: 1, y0: 15, x1: 48, y1: 18 };

export function isInCorridor(x: number, y: number): boolean {
  const inV = x >= CORRIDOR_V.x0 && x <= CORRIDOR_V.x1 && y >= CORRIDOR_V.y0 && y <= CORRIDOR_V.y1;
  const inH = x >= CORRIDOR_H.x0 && x <= CORRIDOR_H.x1 && y >= CORRIDOR_H.y0 && y <= CORRIDOR_H.y1;
  return inV || inH;
}

// ── Door positions ──────────────────────────────────────────────────────────

/** Main entrance door at top of vertical corridor */
export const DOOR_POS = { x: 24, y: 0 };

/** Door gaps connecting rooms to corridors (walkable holes in partition walls) */
export const ROOM_DOORS = {
  // Room → vertical corridor
  claude_v:  { x: 22, y: 7 },
  gemini_v:  { x: 27, y: 7 },
  codex_v:   { x: 22, y: 26 },
  rest_v:    { x: 27, y: 26 },
  // Room → horizontal corridor
  claude_h:  { x: 11, y: 14 },
  gemini_h:  { x: 38, y: 14 },
  codex_h:   { x: 11, y: 19 },
  rest_h:    { x: 38, y: 19 },
};

// ── Legacy compat (REST_AREA / REST_DOOR for Pathfinding/Renderer) ──────────

/** Rest area bounds — now the bottom-right room */
export const REST_AREA = { x0: 28, y0: 20, x1: 48, y1: 32 };

/** Rest room door — primary entrance from vertical corridor */
export const REST_DOOR = ROOM_DOORS.rest_v;

// ── Types ───────────────────────────────────────────────────────────────────

export interface TileMapData {
  width: number;   // in tiles
  height: number;  // in tiles
  walkable: boolean[][];
}

export interface SeatDef {
  tileX: number;
  tileY: number;
  direction: 'up' | 'down' | 'left' | 'right';
  room: RoomId;
}

export interface FurnitureDef {
  type: 'desk' | 'plant' | 'shelf' | 'sofa' | 'wall' | 'clock' | 'bookshelf' | 'bed' | 'water_dispenser' | 'coffee_machine' | 'whiteboard' | 'printer' | 'cabinet';
  tileX: number;
  tileY: number;
  w: number;
  h: number;
  rotation?: 0 | 90 | 180 | 270;
}

export interface RestZone {
  seats: { x: number; y: number }[];
}

export interface DoorDef {
  x: number;
  y: number;
}

// ── Grid dimensions ─────────────────────────────────────────────────────────

const W = 50;
const H = 34;

// ── Walkable grid builder ───────────────────────────────────────────────────

function buildWalkableGrid(): boolean[][] {
  const walkable: boolean[][] = [];
  for (let y = 0; y < H; y++) {
    walkable[y] = [];
    for (let x = 0; x < W; x++) {
      walkable[y][x] = false;
    }
  }

  // Room interiors
  for (const room of ROOMS) {
    for (let y = room.y0; y <= room.y1; y++) {
      for (let x = room.x0; x <= room.x1; x++) {
        walkable[y][x] = true;
      }
    }
  }

  // Vertical corridor
  for (let y = CORRIDOR_V.y0; y <= CORRIDOR_V.y1; y++) {
    for (let x = CORRIDOR_V.x0; x <= CORRIDOR_V.x1; x++) {
      walkable[y][x] = true;
    }
  }

  // Horizontal corridor
  for (let y = CORRIDOR_H.y0; y <= CORRIDOR_H.y1; y++) {
    for (let x = CORRIDOR_H.x0; x <= CORRIDOR_H.x1; x++) {
      walkable[y][x] = true;
    }
  }

  // Door gaps in partition walls
  for (const door of Object.values(ROOM_DOORS)) {
    walkable[door.y][door.x] = true;
  }

  // Main entrance door
  walkable[DOOR_POS.y][DOOR_POS.x] = true;
  walkable[DOOR_POS.y][DOOR_POS.x + 1] = true;

  return walkable;
}

// ── Default office layout ───────────────────────────────────────────────────

export function createDefaultOffice(): {
  map: TileMapData;
  furniture: FurnitureDef[];
  seats: SeatDef[];
  restZone: RestZone;
  door: DoorDef;
} {
  const walkable = buildWalkableGrid();

  const furniture: FurnitureDef[] = [
    // ══════════════════════════════════════════════════════════
    // Claude Code Studio (top-left: x=1..21, y=1..13)
    // ══════════════════════════════════════════════════════════
    // Desks: 3 columns × 3 rows = 9 desks, 18 seats
    { type: 'desk',  tileX: 4,  tileY: 3,  w: 2, h: 1 },
    { type: 'desk',  tileX: 10, tileY: 3,  w: 2, h: 1 },
    { type: 'desk',  tileX: 16, tileY: 3,  w: 2, h: 1 },
    { type: 'desk',  tileX: 4,  tileY: 7,  w: 2, h: 1 },
    { type: 'desk',  tileX: 10, tileY: 7,  w: 2, h: 1 },
    { type: 'desk',  tileX: 16, tileY: 7,  w: 2, h: 1 },
    { type: 'desk',  tileX: 4,  tileY: 11, w: 2, h: 1 },
    { type: 'desk',  tileX: 10, tileY: 11, w: 2, h: 1 },
    { type: 'desk',  tileX: 16, tileY: 11, w: 2, h: 1 },
    // Furniture
    { type: 'clock',     tileX: 5,  tileY: 0,  w: 1, h: 1 },
    { type: 'whiteboard', tileX: 14, tileY: 0,  w: 2, h: 1 },
    { type: 'bookshelf', tileX: 1,  tileY: 3,  w: 1, h: 2 },
    { type: 'bookshelf', tileX: 1,  tileY: 7,  w: 1, h: 2 },
    { type: 'plant',     tileX: 1,  tileY: 1,  w: 1, h: 1 },
    { type: 'plant',     tileX: 21, tileY: 1,  w: 1, h: 1 },
    { type: 'plant',     tileX: 1,  tileY: 13, w: 1, h: 1 },
    { type: 'printer',   tileX: 20, tileY: 5,  w: 1, h: 2 },
    { type: 'cabinet',   tileX: 20, tileY: 9,  w: 1, h: 2 },

    // ══════════════════════════════════════════════════════════
    // Gemini Research Lab (top-right: x=28..48, y=1..13)
    // ══════════════════════════════════════════════════════════
    // Desks: 3 columns × 3 rows = 9 desks, 18 seats
    { type: 'desk',  tileX: 31, tileY: 3,  w: 2, h: 1 },
    { type: 'desk',  tileX: 37, tileY: 3,  w: 2, h: 1 },
    { type: 'desk',  tileX: 43, tileY: 3,  w: 2, h: 1 },
    { type: 'desk',  tileX: 31, tileY: 7,  w: 2, h: 1 },
    { type: 'desk',  tileX: 37, tileY: 7,  w: 2, h: 1 },
    { type: 'desk',  tileX: 43, tileY: 7,  w: 2, h: 1 },
    { type: 'desk',  tileX: 31, tileY: 11, w: 2, h: 1 },
    { type: 'desk',  tileX: 37, tileY: 11, w: 2, h: 1 },
    { type: 'desk',  tileX: 43, tileY: 11, w: 2, h: 1 },
    // Furniture
    { type: 'whiteboard', tileX: 34, tileY: 0,  w: 2, h: 1 },
    { type: 'whiteboard', tileX: 42, tileY: 0,  w: 2, h: 1 },
    { type: 'bookshelf', tileX: 28, tileY: 3,  w: 1, h: 2 },
    { type: 'bookshelf', tileX: 28, tileY: 7,  w: 1, h: 2 },
    { type: 'bookshelf', tileX: 28, tileY: 11, w: 1, h: 2 },
    { type: 'plant',     tileX: 28, tileY: 1,  w: 1, h: 1 },
    { type: 'plant',     tileX: 48, tileY: 1,  w: 1, h: 1 },
    { type: 'plant',     tileX: 48, tileY: 13, w: 1, h: 1 },
    { type: 'cabinet',   tileX: 47, tileY: 5,  w: 1, h: 2 },

    // ══════════════════════════════════════════════════════════
    // Codex Build Lab (bottom-left: x=1..21, y=20..32)
    // ══════════════════════════════════════════════════════════
    // Desks: 3 columns × 3 rows = 9 desks, 18 seats
    { type: 'desk',  tileX: 4,  tileY: 22, w: 2, h: 1 },
    { type: 'desk',  tileX: 10, tileY: 22, w: 2, h: 1 },
    { type: 'desk',  tileX: 16, tileY: 22, w: 2, h: 1 },
    { type: 'desk',  tileX: 4,  tileY: 26, w: 2, h: 1 },
    { type: 'desk',  tileX: 10, tileY: 26, w: 2, h: 1 },
    { type: 'desk',  tileX: 16, tileY: 26, w: 2, h: 1 },
    { type: 'desk',  tileX: 4,  tileY: 30, w: 2, h: 1 },
    { type: 'desk',  tileX: 10, tileY: 30, w: 2, h: 1 },
    { type: 'desk',  tileX: 16, tileY: 30, w: 2, h: 1 },
    // Furniture
    { type: 'whiteboard', tileX: 8,  tileY: 19, w: 2, h: 1 },
    { type: 'printer',    tileX: 20, tileY: 22, w: 1, h: 2 },
    { type: 'printer',    tileX: 20, tileY: 28, w: 1, h: 2 },
    { type: 'bookshelf',  tileX: 1,  tileY: 22, w: 1, h: 2 },
    { type: 'bookshelf',  tileX: 1,  tileY: 26, w: 1, h: 2 },
    { type: 'plant',      tileX: 1,  tileY: 20, w: 1, h: 1 },
    { type: 'plant',      tileX: 21, tileY: 20, w: 1, h: 1 },
    { type: 'plant',      tileX: 1,  tileY: 32, w: 1, h: 1 },
    { type: 'cabinet',    tileX: 20, tileY: 25, w: 1, h: 2 },

    // ══════════════════════════════════════════════════════════
    // Rest / Break Room (bottom-right: x=28..48, y=20..32)
    // ══════════════════════════════════════════════════════════
    { type: 'coffee_machine',  tileX: 28, tileY: 20, w: 1, h: 1 },
    { type: 'water_dispenser', tileX: 30, tileY: 20, w: 1, h: 2 },
    { type: 'bed',             tileX: 42, tileY: 21, w: 2, h: 1 },
    { type: 'bed',             tileX: 42, tileY: 24, w: 2, h: 1 },
    { type: 'bed',             tileX: 42, tileY: 27, w: 2, h: 1 },
    { type: 'sofa',            tileX: 32, tileY: 23, w: 2, h: 1 },
    { type: 'sofa',            tileX: 32, tileY: 27, w: 2, h: 1 },
    { type: 'sofa',            tileX: 36, tileY: 25, w: 2, h: 1 },
    { type: 'plant',           tileX: 48, tileY: 20, w: 1, h: 1 },
    { type: 'plant',           tileX: 28, tileY: 32, w: 1, h: 1 },
    { type: 'plant',           tileX: 48, tileY: 32, w: 1, h: 1 },
    { type: 'bookshelf',       tileX: 46, tileY: 20, w: 1, h: 2 },

    // ══════════════════════════════════════════════════════════
    // Corridor decoration
    // ══════════════════════════════════════════════════════════
    { type: 'plant', tileX: 23, tileY: 1,  w: 1, h: 1 },
    { type: 'plant', tileX: 26, tileY: 1,  w: 1, h: 1 },
    { type: 'plant', tileX: 23, tileY: 32, w: 1, h: 1 },
    { type: 'plant', tileX: 26, tileY: 32, w: 1, h: 1 },

    // ══════════════════════════════════════════════════════════
    // Partition walls (furniture walls at room boundaries)
    // Left partition (x=22): separates left rooms from vertical corridor
    // ══════════════════════════════════════════════════════════
    // Claude studio → corridor (gap at y=7)
    ...partitionWallV(22, 1, 13, [7]),
    // Codex lab → corridor (gap at y=26)
    ...partitionWallV(22, 20, 32, [26]),
    // Right partition (x=27): separates right rooms from vertical corridor
    // Gemini lab → corridor (gap at y=7)
    ...partitionWallV(27, 1, 13, [7]),
    // Rest room → corridor (gap at y=26)
    ...partitionWallV(27, 20, 32, [26]),
    // Top partition (y=14): separates top rooms from horizontal corridor
    // Claude studio (gap at x=11)
    ...partitionWallH(14, 1, 21, [11]),
    // Gemini lab (gap at x=38)
    ...partitionWallH(14, 28, 48, [38]),
    // Bottom partition (y=19): separates bottom rooms from horizontal corridor
    // Codex lab (gap at x=11)
    ...partitionWallH(19, 1, 21, [11]),
    // Rest room (gap at x=38)
    ...partitionWallH(19, 28, 48, [38]),

    // Corner wall blocks where vertical and horizontal partitions meet
    { type: 'wall', tileX: 22, tileY: 14, w: 1, h: 1, rotation: 90 },
    { type: 'wall', tileX: 22, tileY: 19, w: 1, h: 1, rotation: 90 },
    { type: 'wall', tileX: 27, tileY: 14, w: 1, h: 1, rotation: 270 },
    { type: 'wall', tileX: 27, tileY: 19, w: 1, h: 1, rotation: 270 },
  ];

  // Mark furniture tiles as non-walkable
  for (const f of furniture) {
    const rot = f.rotation ?? 0;
    const rw = (rot === 90 || rot === 270) ? f.h : f.w;
    const rh = (rot === 90 || rot === 270) ? f.w : f.h;
    for (let dy = 0; dy < rh; dy++) {
      for (let dx = 0; dx < rw; dx++) {
        const ny = f.tileY + dy, nx = f.tileX + dx;
        if (ny >= 0 && ny < H && nx >= 0 && nx < W) {
          walkable[ny][nx] = false;
        }
      }
    }
  }

  // Restore door gaps after furniture blocking
  for (const door of Object.values(ROOM_DOORS)) {
    walkable[door.y][door.x] = true;
  }
  walkable[DOOR_POS.y][DOOR_POS.x] = true;
  walkable[DOOR_POS.y][DOOR_POS.x + 1] = true;

  // ── Seats ─────────────────────────────────────────────────

  const seats: SeatDef[] = [
    // Claude Code Studio (18 seats: 9 desks × 2)
    ...deskSeats(4, 3, 'claude_studio'),   ...deskSeats(10, 3, 'claude_studio'),  ...deskSeats(16, 3, 'claude_studio'),
    ...deskSeats(4, 7, 'claude_studio'),   ...deskSeats(10, 7, 'claude_studio'),  ...deskSeats(16, 7, 'claude_studio'),
    ...deskSeats(4, 11, 'claude_studio'),  ...deskSeats(10, 11, 'claude_studio'), ...deskSeats(16, 11, 'claude_studio'),

    // Gemini Research Lab (18 seats)
    ...deskSeats(31, 3, 'gemini_lab'),     ...deskSeats(37, 3, 'gemini_lab'),    ...deskSeats(43, 3, 'gemini_lab'),
    ...deskSeats(31, 7, 'gemini_lab'),     ...deskSeats(37, 7, 'gemini_lab'),    ...deskSeats(43, 7, 'gemini_lab'),
    ...deskSeats(31, 11, 'gemini_lab'),    ...deskSeats(37, 11, 'gemini_lab'),   ...deskSeats(43, 11, 'gemini_lab'),

    // Codex Build Lab (18 seats)
    ...deskSeats(4, 22, 'codex_lab'),      ...deskSeats(10, 22, 'codex_lab'),    ...deskSeats(16, 22, 'codex_lab'),
    ...deskSeats(4, 26, 'codex_lab'),      ...deskSeats(10, 26, 'codex_lab'),    ...deskSeats(16, 26, 'codex_lab'),
    ...deskSeats(4, 30, 'codex_lab'),      ...deskSeats(10, 30, 'codex_lab'),    ...deskSeats(16, 30, 'codex_lab'),
  ];

  // Rest zone lounge spots (around beds, sofas, machines)
  const restZone: RestZone = {
    seats: [
      { x: 29, y: 21 }, { x: 31, y: 21 },   // near coffee/water
      { x: 41, y: 21 }, { x: 41, y: 24 },   // near beds
      { x: 41, y: 27 }, { x: 44, y: 22 },
      { x: 34, y: 23 }, { x: 34, y: 27 },   // near sofas
      { x: 38, y: 25 }, { x: 36, y: 22 },
      { x: 32, y: 30 }, { x: 38, y: 30 },   // open floor
      { x: 44, y: 30 }, { x: 29, y: 29 },
      { x: 35, y: 29 }, { x: 40, y: 29 },
    ],
  };

  const door: DoorDef = { x: DOOR_POS.x, y: DOOR_POS.y };

  return { map: { width: W, height: H, walkable }, furniture, seats, restZone, door };
}

// ── Helpers ─────────────────────────────────────────────────────────────────

/** Generate 2 seats in front of a 2-wide desk (facing up) */
function deskSeats(deskX: number, deskY: number, room: RoomId): SeatDef[] {
  return [
    { tileX: deskX,     tileY: deskY + 1, direction: 'up', room },
    { tileX: deskX + 1, tileY: deskY + 1, direction: 'up', room },
  ];
}

/** Generate vertical partition wall segments with door gaps */
function partitionWallV(x: number, y0: number, y1: number, gaps: number[]): FurnitureDef[] {
  const walls: FurnitureDef[] = [];
  for (let y = y0; y <= y1; y++) {
    if (gaps.includes(y)) continue;
    walls.push({ type: 'wall', tileX: x, tileY: y, w: 1, h: 1, rotation: 90 });
  }
  return walls;
}

/** Generate horizontal partition wall segments with door gaps */
function partitionWallH(y: number, x0: number, x1: number, gaps: number[]): FurnitureDef[] {
  const walls: FurnitureDef[] = [];
  for (let x = x0; x <= x1; x++) {
    if (gaps.includes(x)) continue;
    walls.push({ type: 'wall', tileX: x, tileY: y, w: 1, h: 1, rotation: 0 });
  }
  return walls;
}

/** Map CLI type to preferred room */
export function cliToRoom(cliType: string): RoomId {
  switch (cliType) {
    case 'claude': return 'claude_studio';
    case 'codex':  return 'codex_lab';
    case 'gemini': return 'gemini_lab';
    default:       return 'claude_studio';
  }
}

// ── Rebuild walkable grid (for layout persistence) ──────────────────────────

export function rebuildWalkableGrid(gridW: number, gridH: number, furniture: FurnitureDef[]): boolean[][] {
  const walkable: boolean[][] = [];
  for (let y = 0; y < gridH; y++) {
    walkable[y] = [];
    for (let x = 0; x < gridW; x++) walkable[y][x] = false;
  }

  // Room interiors
  for (const room of ROOMS) {
    for (let y = room.y0; y <= Math.min(room.y1, gridH - 1); y++) {
      for (let x = room.x0; x <= Math.min(room.x1, gridW - 1); x++) {
        walkable[y][x] = true;
      }
    }
  }

  // Vertical corridor
  for (let y = CORRIDOR_V.y0; y <= Math.min(CORRIDOR_V.y1, gridH - 1); y++) {
    for (let x = CORRIDOR_V.x0; x <= Math.min(CORRIDOR_V.x1, gridW - 1); x++) {
      walkable[y][x] = true;
    }
  }

  // Horizontal corridor
  for (let y = CORRIDOR_H.y0; y <= Math.min(CORRIDOR_H.y1, gridH - 1); y++) {
    for (let x = CORRIDOR_H.x0; x <= Math.min(CORRIDOR_H.x1, gridW - 1); x++) {
      walkable[y][x] = true;
    }
  }

  // Door gaps
  for (const door of Object.values(ROOM_DOORS)) {
    if (door.y < gridH && door.x < gridW) walkable[door.y][door.x] = true;
  }
  if (DOOR_POS.y < gridH && DOOR_POS.x < gridW) {
    walkable[DOOR_POS.y][DOOR_POS.x] = true;
    if (DOOR_POS.x + 1 < gridW) walkable[DOOR_POS.y][DOOR_POS.x + 1] = true;
  }

  // Furniture → non-walkable
  for (const f of furniture) {
    const rot = f.rotation ?? 0;
    const rw = (rot === 90 || rot === 270) ? f.h : f.w;
    const rh = (rot === 90 || rot === 270) ? f.w : f.h;
    for (let dy = 0; dy < rh; dy++) {
      for (let dx = 0; dx < rw; dx++) {
        const ny = f.tileY + dy, nx = f.tileX + dx;
        if (ny < gridH && nx < gridW) walkable[ny][nx] = false;
      }
    }
  }

  // Restore door gaps
  for (const door of Object.values(ROOM_DOORS)) {
    if (door.y < gridH && door.x < gridW) walkable[door.y][door.x] = true;
  }
  if (DOOR_POS.y < gridH && DOOR_POS.x < gridW) {
    walkable[DOOR_POS.y][DOOR_POS.x] = true;
    if (DOOR_POS.x + 1 < gridW) walkable[DOOR_POS.y][DOOR_POS.x + 1] = true;
  }

  return walkable;
}
