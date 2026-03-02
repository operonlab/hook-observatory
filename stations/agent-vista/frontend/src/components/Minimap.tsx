// Minimap overlay — small canvas in bottom-right showing office overview and viewport
// Agent dots: blue=claude, green=codex, purple=gemini
// White rectangle = current viewport

import { useRef, useEffect, useCallback } from 'react';
import { useAgentStore } from '../stores/agentStore';
import { useOfficeStore } from '../stores/officeStore';
import { TILE } from '../engine/TileMap';
import type { Camera } from '../engine/Camera';
import { useBreakpoint } from '../hooks/useBreakpoint';

const MINIMAP_SCALE_DESKTOP = 4;
const MINIMAP_SCALE_TABLET = 3;

const CLI_COLORS: Record<string, string> = {
  claude: '#4A90D9',
  codex: '#4CAF50',
  gemini: '#9C27B0',
};

interface Props {
  cameraRef: React.RefObject<Camera | null>;
  canvasWidth: number;
  canvasHeight: number;
}

export default function Minimap({ cameraRef, canvasWidth, canvasHeight }: Props) {
  const mmRef = useRef<HTMLCanvasElement>(null);
  useAgentStore(s => s.agents);
  const map = useOfficeStore(s => s.map);
  const furniture = useOfficeStore(s => s.furniture);
  const rafRef = useRef(0);
  const bp = useBreakpoint();
  const MINIMAP_SCALE = bp === 'tablet' ? MINIMAP_SCALE_TABLET : MINIMAP_SCALE_DESKTOP;

  const draw = useCallback(() => {
    const canvas = mmRef.current;
    const camera = cameraRef.current;
    if (!canvas || !camera) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const W = map.width;
    const H = map.height;
    const S = MINIMAP_SCALE;
    const dpr = Math.min(devicePixelRatio || 1, 2);

    // DPR-aware canvas sizing
    const logW = W * S;
    const logH = H * S;
    const bufW = Math.round(logW * dpr);
    const bufH = Math.round(logH * dpr);
    if (canvas.width !== bufW || canvas.height !== bufH) {
      canvas.width = bufW;
      canvas.height = bufH;
      canvas.style.width = logW + 'px';
      canvas.style.height = logH + 'px';
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    // Clear
    ctx.clearRect(0, 0, logW, logH);

    // Background
    ctx.fillStyle = 'rgba(20, 20, 35, 0.85)';
    ctx.fillRect(0, 0, logW, logH);

    // Draw floor tiles (walkable = lighter)
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        if (map.walkable[y] && map.walkable[y][x]) {
          ctx.fillStyle = 'rgba(60, 60, 80, 0.6)';
          ctx.fillRect(x * S, y * S, S, S);
        }
      }
    }

    // Draw furniture as dark blocks
    for (const f of furniture) {
      const rot = f.rotation ?? 0;
      const rw = (rot === 90 || rot === 270) ? f.h : f.w;
      const rh = (rot === 90 || rot === 270) ? f.w : f.h;
      ctx.fillStyle = 'rgba(80, 80, 100, 0.5)';
      ctx.fillRect(f.tileX * S, f.tileY * S, rw * S, rh * S);
    }

    // Draw agents as colored dots
    // pixelX/pixelY are tile-unit coordinates (fractional)
    // minimapX = pixelX * MINIMAP_SCALE
    const { agents: agentMap } = useAgentStore.getState();
    for (const [, entry] of agentMap) {
      const color = CLI_COLORS[entry.agent.cli_type] ?? '#888';
      const dx = entry.fsm.pixelX * S;
      const dy = entry.fsm.pixelY * S;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(dx + S / 2, dy + S / 2, 2.5, 0, Math.PI * 2);
      ctx.fill();
    }

    // Draw viewport rectangle
    const vp = camera.getViewportRect(canvasWidth, canvasHeight);
    // Convert world pixel coords to minimap coords: worldPx / TILE * S
    const vpx = (vp.x / TILE) * S;
    const vpy = (vp.y / TILE) * S;
    const vpw = (vp.w / TILE) * S;
    const vph = (vp.h / TILE) * S;
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.7)';
    ctx.lineWidth = 1;
    ctx.strokeRect(vpx, vpy, vpw, vph);

    // Border
    ctx.strokeStyle = 'rgba(100, 100, 120, 0.5)';
    ctx.lineWidth = 1;
    ctx.strokeRect(0, 0, logW, logH);

    rafRef.current = requestAnimationFrame(draw);
  }, [cameraRef, map, furniture, canvasWidth, canvasHeight, MINIMAP_SCALE]);

  useEffect(() => {
    rafRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(rafRef.current);
  }, [draw]);

  // Click on minimap to navigate camera
  const handleClick = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const camera = cameraRef.current;
    if (!camera) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    // Convert minimap coords to world pixel coords
    const wx = (mx / MINIMAP_SCALE) * TILE;
    const wy = (my / MINIMAP_SCALE) * TILE;
    camera.centerOn(wx, wy, canvasWidth, canvasHeight);
  }, [cameraRef, canvasWidth, canvasHeight]);

  return (
    <canvas
      ref={mmRef}
      onClick={handleClick}
      style={{
        position: 'fixed',
        top: 12,
        left: 12,
        borderRadius: 6,
        border: '1px solid rgba(100, 100, 120, 0.3)',
        cursor: 'crosshair',
        zIndex: 15,
        boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
        imageRendering: 'pixelated',
      }}
    />
  );
}
