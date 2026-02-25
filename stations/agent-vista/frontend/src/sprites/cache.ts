// Render indexed-color sprite frames to offscreen canvases and cache per palette+zoom

import type { ColorPalette } from './palette';
import type { SpriteFrame } from './templates';

const INDEX_TO_KEY: Record<number, keyof ColorPalette | null> = {
  0: null,        // transparent
  1: 'skin',
  2: 'hair',
  3: 'primary',
  4: 'secondary',
  5: 'shoes',
  6: 'outline',
  7: 'eyes',
  8: 'badge',
};

// Cache key: palette hash + zoom + frame identity
const cache = new Map<string, OffscreenCanvas>();

function paletteHash(p: ColorPalette): string {
  return `${p.primary}${p.secondary}${p.hair}`;
}

/** Render a sprite frame at a given zoom level with the given color palette. */
export function renderSprite(
  frame: SpriteFrame,
  palette: ColorPalette,
  zoom: number,
  flipH = false,
): OffscreenCanvas {
  const frameId = frame.length > 0 ? frame[0].join('') + frame.length : 'empty';
  const cacheKey = `${paletteHash(palette)}_${zoom}_${flipH ? 'f' : 'n'}_${frameId}`;

  const cached = cache.get(cacheKey);
  if (cached) return cached;

  const h = frame.length;
  const w = h > 0 ? frame[0].length : 0;
  const canvas = new OffscreenCanvas(w * zoom, h * zoom);
  const ctx = canvas.getContext('2d')!;

  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const idx = frame[y][flipH ? w - 1 - x : x];
      const colorKey = INDEX_TO_KEY[idx];
      if (!colorKey) continue;
      ctx.fillStyle = palette[colorKey];
      ctx.fillRect(x * zoom, y * zoom, zoom, zoom);
    }
  }

  cache.set(cacheKey, canvas);
  return canvas;
}

/** Render a furniture sprite with a simple brown/green palette. */
export function renderFurniture(
  frame: SpriteFrame,
  type: string,
  zoom: number,
): OffscreenCanvas {
  const cacheKey = `furn_${type}_${zoom}`;
  const cached = cache.get(cacheKey);
  if (cached) return cached;

  const palettes: Record<string, Record<number, string>> = {
    desk: { 3: '#8B6914', 4: '#A0782C', 5: '#87CEEB', 6: '#3A2A0A' },
    plant: { 3: '#4CAF50', 4: '#388E3C', 5: '#8D6E63', 6: '#5D4037' },
    shelf: { 3: '#8B6914', 4: '#A0782C', 5: '#5A4510', 6: '#3A2A0A' },
    sofa: { 3: '#6A5ACD', 4: '#483D8B', 5: '#2F2F5A', 6: '#1A1A35' },
    clock: { 3: '#F5F5DC', 4: '#2C2C2C', 5: '#CC3333', 6: '#B8860B' },
    bookshelf: { 3: '#CD853F', 4: '#8B4513', 5: '#654321', 6: '#4A3520' },
    bed: { 3: '#E8E8FF', 4: '#9090C0', 5: '#B8860B', 6: '#483D8B' },
    water_dispenser: { 3: '#E0E0E0', 4: '#B0B0B0', 5: '#4FC3F7', 6: '#757575' },
    coffee_machine: { 3: '#4E342E', 4: '#3E2723', 5: '#FF6F00', 6: '#212121' },
    whiteboard: { 3: '#F0F0F0', 4: '#E0E0E0', 5: '#FF6B6B', 6: '#5A5A5A' },
    printer: { 3: '#404040', 4: '#606060', 5: '#F5F5F5', 6: '#2A2A2A' },
    cabinet: { 3: '#708090', 4: '#A0A0B0', 5: '#C0C0C0', 6: '#4A4A5A' },
  };
  const pal = palettes[type] ?? palettes.desk;

  const h = frame.length;
  const w = h > 0 ? frame[0].length : 0;
  const canvas = new OffscreenCanvas(w * zoom, h * zoom);
  const ctx = canvas.getContext('2d')!;

  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const idx = frame[y][x];
      const color = pal[idx];
      if (!color) continue;
      ctx.fillStyle = color;
      ctx.fillRect(x * zoom, y * zoom, zoom, zoom);
    }
  }

  cache.set(cacheKey, canvas);
  return canvas;
}

/** Clear cache (call on zoom change). */
export function clearSpriteCache() {
  cache.clear();
}
