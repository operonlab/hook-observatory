import { describe, it, expect } from 'vitest';
import { bfsPath, randomNeighbor, randomWalkable } from '../Pathfinding';
import type { TileMapData } from '../TileMap';

function makeMap(w: number, h: number, blocked: [number, number][] = []): TileMapData {
  const walkable: boolean[][] = [];
  for (let y = 0; y < h; y++) {
    walkable[y] = [];
    for (let x = 0; x < w; x++) {
      walkable[y][x] = true;
    }
  }
  for (const [bx, by] of blocked) {
    walkable[by][bx] = false;
  }
  return { width: w, height: h, walkable };
}

describe('bfsPath', () => {
  it('finds direct path on open grid', () => {
    const map = makeMap(5, 5);
    const path = bfsPath(map, { x: 0, y: 0 }, { x: 4, y: 0 }, new Set());
    expect(path).not.toBeNull();
    expect(path!.length).toBe(4);
    expect(path![path!.length - 1]).toEqual({ x: 4, y: 0 });
  });

  it('returns empty array when start === end', () => {
    const map = makeMap(5, 5);
    const path = bfsPath(map, { x: 2, y: 2 }, { x: 2, y: 2 }, new Set());
    expect(path).toEqual([]);
  });

  it('returns null when no path exists', () => {
    // Wall blocking all access to (4,0)
    const map = makeMap(5, 5, [[3, 0], [4, 1]]);
    const blocked = new Set(['3,1']);
    const path = bfsPath(map, { x: 0, y: 0 }, { x: 4, y: 0 }, blocked);
    expect(path).toBeNull();
  });

  it('navigates around obstacles', () => {
    // Wall at (2,0), (2,1), (2,2) — must go around
    const map = makeMap(5, 5, [[2, 0], [2, 1], [2, 2]]);
    const path = bfsPath(map, { x: 0, y: 0 }, { x: 4, y: 0 }, new Set());
    expect(path).not.toBeNull();
    // Path must go down, around, and back up
    expect(path!.length).toBeGreaterThan(4);
    expect(path![path!.length - 1]).toEqual({ x: 4, y: 0 });
  });

  it('respects blocked set', () => {
    const map = makeMap(3, 1);
    const blocked = new Set(['1,0']);
    const path = bfsPath(map, { x: 0, y: 0 }, { x: 2, y: 0 }, blocked);
    expect(path).toBeNull();
  });

  it('returns null when end is outside map', () => {
    const map = makeMap(3, 3);
    const path = bfsPath(map, { x: 0, y: 0 }, { x: 5, y: 5 }, new Set());
    expect(path).toBeNull();
  });
});

describe('randomNeighbor', () => {
  it('returns a walkable adjacent tile', () => {
    const map = makeMap(5, 5);
    const pos = { x: 2, y: 2 };
    const result = randomNeighbor(map, pos, new Set());
    expect(result).not.toBeNull();
    const dx = Math.abs(result!.x - pos.x);
    const dy = Math.abs(result!.y - pos.y);
    expect(dx + dy).toBe(1);
  });

  it('returns null when surrounded', () => {
    const map = makeMap(3, 3, [[0, 1], [1, 0], [2, 1], [1, 2]]);
    const result = randomNeighbor(map, { x: 1, y: 1 }, new Set());
    expect(result).toBeNull();
  });
});

describe('randomWalkable', () => {
  it('returns a walkable tile', () => {
    const map = makeMap(5, 5);
    const result = randomWalkable(map, new Set());
    expect(result).not.toBeNull();
    expect(map.walkable[result!.y][result!.x]).toBe(true);
  });

  it('returns null when no walkable tiles', () => {
    const blocked = new Set<string>();
    const map = makeMap(2, 2, [[0, 0], [0, 1], [1, 0], [1, 1]]);
    const result = randomWalkable(map, blocked);
    expect(result).toBeNull();
  });
});
