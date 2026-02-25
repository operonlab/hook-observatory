import { describe, it, expect } from 'vitest';
import { createDefaultOffice, TILE } from '../TileMap';

describe('createDefaultOffice', () => {
  const { map, furniture, seats } = createDefaultOffice();

  it('creates 50x34 tile map', () => {
    expect(map.width).toBe(50);
    expect(map.height).toBe(34);
  });

  it('has walls on outer edges (except door gaps)', () => {
    // Left and right columns are always non-walkable
    for (let y = 0; y < map.height; y++) {
      expect(map.walkable[y][0]).toBe(false);
      expect(map.walkable[y][map.width - 1]).toBe(false);
    }
    // Bottom row is always non-walkable
    for (let x = 0; x < map.width; x++) {
      expect(map.walkable[map.height - 1][x]).toBe(false);
    }
    // Top row non-walkable except entrance door (x=24,25)
    expect(map.walkable[0][0]).toBe(false);
    expect(map.walkable[0][23]).toBe(false);
    expect(map.walkable[0][24]).toBe(true);  // door
    expect(map.walkable[0][25]).toBe(true);  // door
    expect(map.walkable[0][26]).toBe(false);
  });

  it('marks desk tiles as non-walkable', () => {
    for (const f of furniture) {
      if (f.type !== 'desk') continue;
      for (let dy = 0; dy < f.h; dy++) {
        for (let dx = 0; dx < f.w; dx++) {
          expect(map.walkable[f.tileY + dy][f.tileX + dx]).toBe(false);
        }
      }
    }
  });

  it('places seats on walkable tiles', () => {
    for (const s of seats) {
      expect(map.walkable[s.tileY][s.tileX]).toBe(true);
    }
  });

  it('has at least 6 desks and 8 seats', () => {
    expect(furniture.filter(f => f.type === 'desk').length).toBeGreaterThanOrEqual(6);
    expect(seats.length).toBeGreaterThanOrEqual(8);
  });
});

describe('TILE constant', () => {
  it('is 16', () => {
    expect(TILE).toBe(16);
  });
});
