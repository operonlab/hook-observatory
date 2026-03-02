#!/usr/bin/env node
// Generate PWA icons from the downIdle0 sprite template
// Uses pure Canvas API (node --experimental-vm-modules not needed)
// Output: frontend/public/icons/icon-192.png, icon-512.png

import { createCanvas } from '@napi-rs/canvas';
import { writeFileSync, mkdirSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const outDir = resolve(__dirname, '../public/icons');
mkdirSync(outDir, { recursive: true });

// downIdle0 sprite from templates.ts (10x14 pixels)
// 0=transparent, 1=skin, 2=hair, 3=primary, 4=secondary, 5=shoes, 6=outline, 7=eyes, 8=badge
const sprite = [
  [0,0,0,6,6,6,6,0,0,0],
  [0,0,6,2,2,2,2,6,0,0],
  [0,6,2,2,2,2,2,2,6,0],
  [0,6,1,1,1,1,1,1,6,0],
  [0,6,1,7,1,1,7,1,6,0],
  [0,0,1,1,1,1,1,1,0,0],
  [0,0,0,1,1,1,1,0,0,0],
  [0,0,3,3,8,3,3,3,0,0],
  [0,3,3,3,8,3,3,3,3,0],
  [0,3,3,4,4,4,4,3,3,0],
  [0,0,3,3,3,3,3,3,0,0],
  [0,0,0,1,0,0,1,0,0,0],
  [0,0,0,5,0,0,5,0,0,0],
  [0,0,5,5,0,0,5,5,0,0],
];

// Claude palette (the "default" agent look)
const palette = {
  0: null, // transparent
  1: '#FFD4A0', // skin
  2: '#5C3A1E', // hair
  3: '#4A90D9', // primary (blue)
  4: '#3670B0', // secondary
  5: '#3A3A4A', // shoes
  6: '#2A2A3A', // outline
  7: '#2A2A3A', // eyes
  8: '#4A90D9', // badge
};

const SPRITE_W = 10;
const SPRITE_H = 14;

function renderIcon(size) {
  const canvas = createCanvas(size, size);
  const ctx = canvas.getContext('2d');

  // Background: dark theme matching the app
  ctx.fillStyle = '#1a1a2e';
  ctx.fillRect(0, 0, size, size);

  // Subtle rounded background circle for maskable icon area
  const cx = size / 2;
  const cy = size / 2;
  const radius = size * 0.38;
  ctx.beginPath();
  ctx.arc(cx, cy, radius, 0, Math.PI * 2);
  ctx.fillStyle = 'rgba(74, 144, 217, 0.15)';
  ctx.fill();

  // Calculate pixel scale to fit sprite centered with padding
  const padding = size * 0.2;
  const availW = size - padding * 2;
  const availH = size - padding * 2;
  const pixelSize = Math.floor(Math.min(availW / SPRITE_W, availH / SPRITE_H));

  // Center the sprite
  const offsetX = Math.floor((size - SPRITE_W * pixelSize) / 2);
  const offsetY = Math.floor((size - SPRITE_H * pixelSize) / 2);

  // Draw pixels with nearest-neighbor (crisp pixel art)
  ctx.imageSmoothingEnabled = false;
  for (let y = 0; y < SPRITE_H; y++) {
    for (let x = 0; x < SPRITE_W; x++) {
      const idx = sprite[y][x];
      const color = palette[idx];
      if (!color) continue;
      ctx.fillStyle = color;
      ctx.fillRect(offsetX + x * pixelSize, offsetY + y * pixelSize, pixelSize, pixelSize);
    }
  }

  return canvas.toBuffer('image/png');
}

for (const size of [192, 512]) {
  const buf = renderIcon(size);
  const path = resolve(outDir, `icon-${size}.png`);
  writeFileSync(path, buf);
  console.log(`Generated ${path} (${buf.length} bytes)`);
}
