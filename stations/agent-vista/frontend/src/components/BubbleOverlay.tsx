// Expanded bubble overlay — click character to expand, hover to keep, 10s auto-close

import { useState, useEffect, useRef, useCallback } from 'react';
import { useAgentStore, type AgentEntry } from '../stores/agentStore';
import { useUIStore } from '../stores/uiStore';
import type { Camera } from '../engine/Camera';
import { TILE } from '../engine/TileMap';
import { CHAR_H } from '../sprites/templates';
import { CLI_PALETTES } from '../sprites/palette';
import { parseToolDetail } from '../engine/CharacterFSM';

const BLUR_TIMEOUT = 10_000; // 10s auto-close when not hovering
const STATUS_LABELS: Record<string, string> = {
  active: '工作中', thinking: '思考中', typing: '輸入中',
  reading: '閱讀中', waiting: '等待中', idle: '閒置',
};

const FSM_STATE_LABELS: Record<string, string> = {
  TYPE: '工作中', THINK: '思考中', WAIT: '等待許可',
  IDLE: '閒置', WALK: '移動中', ERROR: '發生錯誤',
};

interface Props {
  canvasRef: React.RefObject<HTMLCanvasElement | null>;
  cameraRef: React.RefObject<Camera | null>;
}

export default function BubbleOverlay({ canvasRef, cameraRef }: Props) {
  const agents = useAgentStore(s => s.agents);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [screenPos, setScreenPos] = useState({ x: 0, y: 0 });
  const hovering = useRef(false);
  const blurTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const rafRef = useRef(0);

  // Hit-test on canvas click (mouse + touch tap)
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    // Track touch start position to distinguish tap from drag
    let touchStartX = 0;
    let touchStartY = 0;
    const TAP_THRESHOLD = 10;

    function hitTest(clientX: number, clientY: number) {
      const camera = cameraRef.current;
      if (!camera) return;
      const { agents: agentMap } = useAgentStore.getState();

      const rect = canvas!.getBoundingClientRect();
      const mx = clientX - rect.left;
      const my = clientY - rect.top;

      let bestId: string | null = null;
      let bestDist = Infinity;

      for (const [id, entry] of agentMap) {
        const fsm = entry.fsm;
        const wx = fsm.pixelX * TILE + TILE / 2;
        const wy = fsm.pixelY * TILE + TILE / 2;
        const { sx, sy } = camera.worldToScreen(wx, wy);

        const dx = mx - sx;
        const dy = my - sy;
        const dist = Math.sqrt(dx * dx + dy * dy);
        const hitRadius = TILE * camera.zoom * 1.5;

        if (dist < hitRadius && dist < bestDist) {
          bestDist = dist;
          bestId = id;
        }
      }

      if (bestId) {
        setExpandedId(prev => {
          const toggled = prev === bestId ? null : bestId;
          useUIStore.getState().selectAgent(toggled);
          return toggled;
        });
      } else {
        setExpandedId(null);
        useUIStore.getState().selectAgent(null);
      }
    }

    function onClick(e: MouseEvent) {
      hitTest(e.clientX, e.clientY);
    }

    function onTouchStart(e: TouchEvent) {
      if (e.touches.length === 1) {
        touchStartX = e.touches[0].clientX;
        touchStartY = e.touches[0].clientY;
      }
    }

    function onTouchEnd(e: TouchEvent) {
      if (e.changedTouches.length === 1) {
        const tx = e.changedTouches[0].clientX;
        const ty = e.changedTouches[0].clientY;
        const dx = tx - touchStartX;
        const dy = ty - touchStartY;
        if (Math.sqrt(dx * dx + dy * dy) < TAP_THRESHOLD) {
          hitTest(tx, ty);
        }
      }
    }

    canvas.addEventListener('click', onClick);
    canvas.addEventListener('touchstart', onTouchStart, { passive: true });
    canvas.addEventListener('touchend', onTouchEnd, { passive: true });
    return () => {
      canvas.removeEventListener('click', onClick);
      canvas.removeEventListener('touchstart', onTouchStart);
      canvas.removeEventListener('touchend', onTouchEnd);
    };
  }, [canvasRef, cameraRef]);

  // Track screen position of expanded agent
  useEffect(() => {
    if (!expandedId) {
      cancelAnimationFrame(rafRef.current);
      return;
    }

    function track() {
      const camera = cameraRef.current;
      const { agents: agentMap } = useAgentStore.getState();
      const entry = agentMap.get(expandedId!);
      if (!camera || !entry) {
        setExpandedId(null);
        return;
      }

      const fsm = entry.fsm;
      const wx = fsm.pixelX * TILE + TILE / 2;
      const wy = fsm.pixelY * TILE - CHAR_H;
      const { sx, sy } = camera.worldToScreen(wx, wy);
      setScreenPos({ x: sx, y: sy });

      rafRef.current = requestAnimationFrame(track);
    }

    rafRef.current = requestAnimationFrame(track);
    return () => cancelAnimationFrame(rafRef.current);
  }, [expandedId, cameraRef]);

  // Auto-close on blur
  const startBlurTimer = useCallback(() => {
    if (blurTimer.current) clearTimeout(blurTimer.current);
    blurTimer.current = setTimeout(() => {
      if (!hovering.current) setExpandedId(null);
    }, BLUR_TIMEOUT);
  }, []);

  useEffect(() => {
    if (expandedId && !hovering.current) startBlurTimer();
    return () => { if (blurTimer.current) clearTimeout(blurTimer.current); };
  }, [expandedId, startBlurTimer]);

  if (!expandedId) return null;

  const entry = agents.get(expandedId);
  if (!entry) return null;

  return (
    <div
      style={{
        position: 'fixed',
        left: screenPos.x,
        top: screenPos.y - 20,
        transform: 'translate(-50%, -100%)',
        zIndex: 20,
        pointerEvents: 'auto',
      }}
      onMouseEnter={() => {
        hovering.current = true;
        if (blurTimer.current) clearTimeout(blurTimer.current);
      }}
      onMouseLeave={() => {
        hovering.current = false;
        startBlurTimer();
      }}
    >
      <ExpandedBubble
        entry={entry}
        onClose={() => setExpandedId(null)}
      />
    </div>
  );
}

function ExpandedBubble({ entry, onClose }: { entry: AgentEntry; onClose: () => void }) {
  const { agent, fsm } = entry;
  const color = CLI_PALETTES[agent.cli_type]?.badge ?? '#666';
  const statusLabel = STATUS_LABELS[agent.status] ?? agent.status;
  const fullText = fsm.bubbleFull ?? fsm.bubble;

  return (
    <div style={panelStyle}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{
            display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
            backgroundColor: color,
          }} />
          <span style={{ color: '#E0E0E0', fontSize: 12, fontWeight: 'bold' }}>
            {agent.display_name}
          </span>
          <span style={{ color: '#888', fontSize: 10 }}>
            {statusLabel}
          </span>
        </div>
        <button onClick={onClose} style={closeStyle}>✕</button>
      </div>

      {/* Tool info */}
      {agent.current_tool && (
        <div style={{ fontSize: 10, color: '#AAA', marginBottom: 4 }}>
          {agent.current_tool}
          {agent.tool_detail && (
            <span style={{ color: '#666' }}> — {parseToolDetail(agent.current_tool, agent.tool_detail) ?? ''}</span>
          )}
        </div>
      )}

      {/* Content */}
      {fullText ? (
        <div style={contentStyle}>{fullText}</div>
      ) : (
        <div style={{ ...contentStyle, color: '#999' }}>
          {agent.current_tool
            ? `${agent.current_tool} — ${parseToolDetail(agent.current_tool, agent.tool_detail) ?? ''}`
            : FSM_STATE_LABELS[fsm.state] ?? '閒置'}
        </div>
      )}

      {/* Token count */}
      {agent.tokens_total > 0 && (
        <div style={{ fontSize: 9, color: '#555', marginTop: 4, textAlign: 'right' }}>
          {agent.tokens_total.toLocaleString()} tokens
        </div>
      )}
    </div>
  );
}

const panelStyle: React.CSSProperties = {
  width: 'min(280px, calc(100vw - 24px))',
  maxWidth: 280,
  maxHeight: 200,
  padding: 10,
  background: 'rgba(20, 20, 35, 0.95)',
  border: '1px solid #444',
  borderRadius: 8,
  fontFamily: 'monospace',
  backdropFilter: 'blur(6px)',
  boxShadow: '0 4px 16px rgba(0,0,0,0.5)',
};

const contentStyle: React.CSSProperties = {
  fontSize: 11,
  color: '#CCC',
  lineHeight: '1.5',
  maxHeight: 120,
  overflowY: 'auto',
  wordBreak: 'break-word',
  whiteSpace: 'pre-wrap',
};

const closeStyle: React.CSSProperties = {
  background: 'none',
  border: 'none',
  color: '#888',
  fontSize: 12,
  cursor: 'pointer',
  padding: '2px 6px',
  borderRadius: 4,
};
