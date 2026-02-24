import { useRef, useEffect, useCallback } from "react";
import type { GalaxyNode, GalaxyLink, BlockType } from "../types";

interface GalaxyCanvasProps {
  nodes: GalaxyNode[];
  links: GalaxyLink[];
  onNodeClick?: (node: GalaxyNode) => void;
  width?: number;
  height?: number;
}

interface SimNode extends GalaxyNode {
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
}

interface ResolvedColors {
  blue: string;
  green: string;
  mauve: string;
  text: string;
  subtext0: string;
  surface0: string;
  base: string;
  mantle: string;
}

const TYPE_COLOR_MAP: Record<BlockType, keyof ResolvedColors> = {
  knowledge: "blue",
  skill: "green",
  attitude: "mauve",
  general: "text",
};

function resolveCssColors(): ResolvedColors {
  const style = getComputedStyle(document.documentElement);
  const get = (v: string) => style.getPropertyValue(v).trim();
  return {
    blue: get("--blue"),
    green: get("--green"),
    mauve: get("--mauve"),
    text: get("--text"),
    subtext0: get("--subtext0"),
    surface0: get("--surface0"),
    base: get("--base"),
    mantle: get("--mantle"),
  };
}

function hexToRgba(hex: string, alpha: number): string {
  if (hex.startsWith("#")) {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r},${g},${b},${alpha})`;
  }
  return hex;
}

// Force simulation constants
const REPULSION = 800;
const ATTRACTION = 0.005;
const CENTER_GRAVITY = 0.01;
const DAMPING = 0.92;
const MIN_NODE_RADIUS = 6;
const MAX_NODE_RADIUS = 18;

export default function GalaxyCanvas({
  nodes,
  links,
  onNodeClick,
  width = 800,
  height = 600,
}: GalaxyCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const simNodesRef = useRef<SimNode[]>([]);
  const animRef = useRef<number>(0);
  const colorsRef = useRef<ResolvedColors | null>(null);
  const hoveredRef = useRef<SimNode | null>(null);
  const mouseRef = useRef({ x: 0, y: 0 });

  // Initialize simulation nodes when input changes
  useEffect(() => {
    const cx = width / 2;
    const cy = height / 2;
    simNodesRef.current = nodes.map((n, i) => {
      const angle = (2 * Math.PI * i) / Math.max(nodes.length, 1);
      const spread = Math.min(width, height) * 0.3;
      return {
        ...n,
        x: n.x ?? cx + Math.cos(angle) * spread * (0.5 + Math.random() * 0.5),
        y: n.y ?? cy + Math.sin(angle) * spread * (0.5 + Math.random() * 0.5),
        vx: n.vx ?? 0,
        vy: n.vy ?? 0,
        radius: MIN_NODE_RADIUS + (MAX_NODE_RADIUS - MIN_NODE_RADIUS) * n.confidence,
      };
    });
  }, [nodes, width, height]);

  // Resolve colors once
  useEffect(() => {
    colorsRef.current = resolveCssColors();
  }, []);

  const findNodeAt = useCallback(
    (mx: number, my: number): SimNode | null => {
      for (let i = simNodesRef.current.length - 1; i >= 0; i--) {
        const n = simNodesRef.current[i];
        const dx = mx - n.x;
        const dy = my - n.y;
        if (dx * dx + dy * dy <= (n.radius + 4) * (n.radius + 4)) {
          return n;
        }
      }
      return null;
    },
    [],
  );

  // Mouse handlers
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const getPos = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      return { x: e.clientX - rect.left, y: e.clientY - rect.top };
    };

    const onMove = (e: MouseEvent) => {
      const pos = getPos(e);
      mouseRef.current = pos;
      const node = findNodeAt(pos.x, pos.y);
      hoveredRef.current = node;
      canvas.style.cursor = node ? "pointer" : "default";
    };

    const onClick = (e: MouseEvent) => {
      const pos = getPos(e);
      const node = findNodeAt(pos.x, pos.y);
      if (node && onNodeClick) onNodeClick(node);
    };

    canvas.addEventListener("mousemove", onMove);
    canvas.addEventListener("click", onClick);
    return () => {
      canvas.removeEventListener("mousemove", onMove);
      canvas.removeEventListener("click", onClick);
    };
  }, [findNodeAt, onNodeClick]);

  // Animation loop
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const maybeCtx = canvas.getContext("2d");
    if (!maybeCtx) return;
    const ctx = maybeCtx;

    const nodeMap = new Map<string, SimNode>();

    function tick() {
      const sn = simNodesRef.current;
      const colors = colorsRef.current;
      if (!colors || sn.length === 0) {
        animRef.current = requestAnimationFrame(tick);
        return;
      }

      nodeMap.clear();
      for (const n of sn) nodeMap.set(n.id, n);

      const cx = width / 2;
      const cy = height / 2;

      // --- Forces ---
      // Repulsion (all pairs)
      for (let i = 0; i < sn.length; i++) {
        for (let j = i + 1; j < sn.length; j++) {
          const a = sn[i];
          const b = sn[j];
          let dx = a.x - b.x;
          let dy = a.y - b.y;
          let dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < 1) { dx = Math.random() - 0.5; dy = Math.random() - 0.5; dist = 1; }
          const force = REPULSION / (dist * dist);
          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;
          a.vx += fx;
          a.vy += fy;
          b.vx -= fx;
          b.vy -= fy;
        }
      }

      // Attraction (links)
      for (const link of links) {
        const a = nodeMap.get(link.source);
        const b = nodeMap.get(link.target);
        if (!a || !b) continue;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const force = ATTRACTION * link.strength;
        a.vx += dx * force;
        a.vy += dy * force;
        b.vx -= dx * force;
        b.vy -= dy * force;
      }

      // Center gravity
      for (const n of sn) {
        n.vx += (cx - n.x) * CENTER_GRAVITY;
        n.vy += (cy - n.y) * CENTER_GRAVITY;
      }

      // Apply damping + update positions
      for (const n of sn) {
        n.vx *= DAMPING;
        n.vy *= DAMPING;
        n.x += n.vx;
        n.y += n.vy;
        // Clamp to canvas bounds
        n.x = Math.max(n.radius, Math.min(width - n.radius, n.x));
        n.y = Math.max(n.radius, Math.min(height - n.radius, n.y));
      }

      // --- Render ---
      ctx.clearRect(0, 0, width, height);

      // Links
      for (const link of links) {
        const a = nodeMap.get(link.source);
        const b = nodeMap.get(link.target);
        if (!a || !b) continue;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.strokeStyle = hexToRgba(colors.surface0, 0.3 + link.strength * 0.5);
        ctx.lineWidth = 1 + link.strength * 2;
        ctx.stroke();
      }

      // Nodes
      const hovered = hoveredRef.current;
      for (const n of sn) {
        const colorKey = TYPE_COLOR_MAP[n.type];
        const fill = colors[colorKey];
        const isHovered = hovered?.id === n.id;

        // Glow for hovered node
        if (isHovered) {
          ctx.beginPath();
          ctx.arc(n.x, n.y, n.radius + 6, 0, Math.PI * 2);
          ctx.fillStyle = hexToRgba(fill, 0.15);
          ctx.fill();
        }

        // Node circle
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.radius, 0, Math.PI * 2);
        ctx.fillStyle = hexToRgba(fill, isHovered ? 1 : 0.8);
        ctx.fill();
        ctx.strokeStyle = hexToRgba(fill, 0.4);
        ctx.lineWidth = 1.5;
        ctx.stroke();

        // Label (only if big enough or hovered)
        if (n.radius >= 10 || isHovered) {
          ctx.font = `${isHovered ? 12 : 10}px system-ui, sans-serif`;
          ctx.fillStyle = colors.text;
          ctx.textAlign = "center";
          ctx.textBaseline = "top";
          const label = n.label.length > 20 ? n.label.slice(0, 18) + "..." : n.label;
          ctx.fillText(label, n.x, n.y + n.radius + 4);
        }
      }

      // Tooltip for hovered node
      if (hovered) {
        const tx = mouseRef.current.x + 12;
        const ty = mouseRef.current.y - 10;
        const text = hovered.label;
        const conf = `${Math.round(hovered.confidence * 100)}%`;
        ctx.font = "11px system-ui, sans-serif";
        const tm = ctx.measureText(text);
        const cm = ctx.measureText(conf);
        const tw = Math.max(tm.width, cm.width) + 16;

        ctx.fillStyle = colors.mantle;
        ctx.strokeStyle = colors.surface0;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.roundRect(tx, ty, tw, 40, 6);
        ctx.fill();
        ctx.stroke();

        ctx.fillStyle = colors.text;
        ctx.textAlign = "left";
        ctx.textBaseline = "top";
        ctx.fillText(text, tx + 8, ty + 6);
        ctx.fillStyle = colors.subtext0;
        ctx.fillText(`${hovered.type} | ${conf}`, tx + 8, ty + 22);
      }

      animRef.current = requestAnimationFrame(tick);
    }

    animRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(animRef.current);
  }, [links, width, height]);

  return (
    <canvas
      ref={canvasRef}
      width={width}
      height={height}
      className="rounded-xl"
      style={{ backgroundColor: "var(--base)" }}
    />
  );
}
