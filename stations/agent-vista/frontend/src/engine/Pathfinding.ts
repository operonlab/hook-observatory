// BFS pathfinding on tile grid

import type { TileMapData } from './TileMap';
import { ROOMS, CORRIDOR_V, CORRIDOR_H, type RoomId } from './TileMap';

export interface GridPos { x: number; y: number }

const DIRS = [
  { x: 0, y: -1 },
  { x: 0, y: 1 },
  { x: -1, y: 0 },
  { x: 1, y: 0 },
];

const key = (p: GridPos) => `${p.x},${p.y}`;

function canWalk(map: TileMapData, p: GridPos, blocked: Set<string>): boolean {
  if (p.x < 0 || p.x >= map.width || p.y < 0 || p.y >= map.height) return false;
  if (!map.walkable[p.y][p.x]) return false;
  if (blocked.has(key(p))) return false;
  return true;
}

/** BFS shortest path from start to end. Returns path (excluding start), or null. */
export function bfsPath(
  map: TileMapData,
  start: GridPos,
  end: GridPos,
  blocked: Set<string>,
): GridPos[] | null {
  if (!canWalk(map, end, blocked)) return null;
  if (start.x === end.x && start.y === end.y) return [];

  const visited = new Set<string>();
  const parent = new Map<string, GridPos>();
  const queue: GridPos[] = [start];
  visited.add(key(start));

  while (queue.length > 0) {
    const cur = queue.shift()!;
    for (const d of DIRS) {
      const next: GridPos = { x: cur.x + d.x, y: cur.y + d.y };
      const nk = key(next);
      if (visited.has(nk) || !canWalk(map, next, blocked)) continue;
      visited.add(nk);
      parent.set(nk, cur);
      if (next.x === end.x && next.y === end.y) {
        const path: GridPos[] = [];
        let node: GridPos | undefined = next;
        while (node && key(node) !== key(start)) {
          path.unshift(node);
          node = parent.get(key(node));
        }
        return path;
      }
      queue.push(next);
    }
  }
  return null;
}

/** Pick a random walkable neighbor (for idle wander). */
export function randomNeighbor(
  map: TileMapData,
  pos: GridPos,
  blocked: Set<string>,
): GridPos | null {
  const opts = DIRS
    .map(d => ({ x: pos.x + d.x, y: pos.y + d.y }))
    .filter(p => canWalk(map, p, blocked));
  return opts.length > 0 ? opts[Math.floor(Math.random() * opts.length)] : null;
}

/** Pick a random walkable tile on the map (for idle wander target). */
export function randomWalkable(map: TileMapData, blocked: Set<string>): GridPos | null {
  const candidates: GridPos[] = [];
  for (let y = 0; y < map.height; y++) {
    for (let x = 0; x < map.width; x++) {
      if (canWalk(map, { x, y }, blocked)) candidates.push({ x, y });
    }
  }
  return candidates.length > 0
    ? candidates[Math.floor(Math.random() * candidates.length)]
    : null;
}

/** Check if a tile is in a specific room */
function inRoom(x: number, y: number, roomId: RoomId): boolean {
  if (roomId === 'corridor') {
    const inV = x >= CORRIDOR_V.x0 && x <= CORRIDOR_V.x1 && y >= CORRIDOR_V.y0 && y <= CORRIDOR_V.y1;
    const inH = x >= CORRIDOR_H.x0 && x <= CORRIDOR_H.x1 && y >= CORRIDOR_H.y0 && y <= CORRIDOR_H.y1;
    return inV || inH;
  }
  const room = ROOMS.find(r => r.id === roomId);
  if (!room) return false;
  return x >= room.x0 && x <= room.x1 && y >= room.y0 && y <= room.y1;
}

/** Pick a random walkable tile in a specific room. */
export function randomWalkableInRoom(
  map: TileMapData,
  blocked: Set<string>,
  roomId: RoomId,
): GridPos | null {
  const candidates: GridPos[] = [];
  for (let y = 0; y < map.height; y++) {
    for (let x = 0; x < map.width; x++) {
      if (!inRoom(x, y, roomId)) continue;
      if (canWalk(map, { x, y }, blocked)) candidates.push({ x, y });
    }
  }
  return candidates.length > 0
    ? candidates[Math.floor(Math.random() * candidates.length)]
    : null;
}

/** Legacy: Pick a random walkable tile constrained to work/rest zone. */
export function randomWalkableInZone(
  map: TileMapData,
  blocked: Set<string>,
  zone: 'work' | 'rest' | RoomId,
  restArea: { x0: number; y0: number; x1: number; y1: number },
): GridPos | null {
  // If zone is a specific room ID, use room-based logic
  if (zone !== 'work' && zone !== 'rest') {
    return randomWalkableInRoom(map, blocked, zone);
  }

  const candidates: GridPos[] = [];
  for (let y = 0; y < map.height; y++) {
    for (let x = 0; x < map.width; x++) {
      const inRest = x >= restArea.x0 && x <= restArea.x1 && y >= restArea.y0 && y <= restArea.y1;
      if (zone === 'work' && inRest) continue;
      if (zone === 'rest' && !inRest) continue;
      if (canWalk(map, { x, y }, blocked)) candidates.push({ x, y });
    }
  }
  return candidates.length > 0
    ? candidates[Math.floor(Math.random() * candidates.length)]
    : null;
}
