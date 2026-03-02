// Side panel — slides in from the right when an agent is selected

import React from 'react';
import { useUIStore } from '../stores/uiStore';
import { useAgentStore } from '../stores/agentStore';
import { CLI_PALETTES } from '../sprites/palette';
import { useBreakpoint } from '../hooks/useBreakpoint';

// ── Helpers ────────────────────────────────────────────────────────────────

function statusColor(status: string): string {
  switch (status) {
    case 'active':
    case 'typing':
    case 'reading':
      return '#4CAF50';
    case 'thinking':
      return '#FFB74D';
    case 'waiting':
      return '#FF5722';
    case 'idle':
    case 'resting':
      return '#666';
    case 'error':
      return '#F44336';
    default:
      return '#888';
  }
}

function statusLabel(status: string, fsmState: string): string {
  const labels: Record<string, string> = {
    active: '工作中',
    thinking: '思考中',
    typing: '輸入中',
    reading: '閱讀中',
    waiting: '等待中',
    idle: '閒置',
    resting: '休息中',
    error: '錯誤',
    offline: '離線',
  };
  return labels[status] ?? fsmState;
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n) + '...' : s;
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

// ── Sub-components ─────────────────────────────────────────────────────────

function Divider() {
  return (
    <div style={{
      height: 1,
      background: '#333',
      margin: '10px 0',
    }} />
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 4 }}>
      <div style={{ color: '#888', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6 }}>
        {title}
      </div>
      {children}
    </div>
  );
}

function TokenRow({ label, value, bold }: { label: string; value: number; bold?: boolean }) {
  return (
    <div style={{
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      marginBottom: 3,
    }}>
      <span style={{ color: '#AAA', fontSize: 11 }}>{label}</span>
      <span style={{
        color: bold ? '#E0E0E0' : '#CCC',
        fontSize: 11,
        fontWeight: bold ? 'bold' : 'normal',
      }}>
        {formatNumber(value)}
      </span>
    </div>
  );
}

// ── Style Constants ─────────────────────────────────────────────────────────

const panelStyle: React.CSSProperties = {
  position: 'fixed',
  right: 0,
  top: 0,
  width: 300,
  height: '100vh',
  background: 'rgba(20, 20, 35, 0.95)',
  borderLeft: '1px solid #333',
  fontFamily: 'monospace',
  padding: 16,
  overflowY: 'auto',
  zIndex: 25,
  backdropFilter: 'blur(6px)',
  boxShadow: '-4px 0 16px rgba(0,0,0,0.3)',
  transition: 'transform 0.2s ease',
  boxSizing: 'border-box',
};

const tabletPanelStyle: React.CSSProperties = {
  ...panelStyle,
  width: 240,
};

const mobileSheetStyle: React.CSSProperties = {
  position: 'fixed',
  bottom: 0,
  left: 0,
  right: 0,
  width: '100%',
  height: '60vh',
  background: 'rgba(20, 20, 35, 0.97)',
  borderTop: '1px solid #333',
  borderRadius: '12px 12px 0 0',
  fontFamily: 'monospace',
  padding: 16,
  overflowY: 'auto',
  zIndex: 25,
  backdropFilter: 'blur(6px)',
  boxShadow: '0 -4px 16px rgba(0,0,0,0.3)',
  boxSizing: 'border-box',
};

const closeBtn: React.CSSProperties = {
  position: 'absolute',
  top: 12,
  right: 12,
  background: 'none',
  border: '1px solid #444',
  color: '#888',
  fontSize: 12,
  cursor: 'pointer',
  padding: '2px 7px',
  borderRadius: 4,
  fontFamily: 'monospace',
  lineHeight: '1.4',
};

const headerStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 10,
  marginBottom: 4,
  paddingRight: 36,
};

const badgeStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  width: 28,
  height: 28,
  borderRadius: 6,
  color: '#FFF',
  fontSize: 13,
  fontWeight: 'bold',
  flexShrink: 0,
};

// ── Main Component ──────────────────────────────────────────────────────────

export default function AgentDetailPanel() {
  const selectedId = useUIStore(s => s.selectedAgentId);
  const detailOpen = useUIStore(s => s.detailPanelOpen);
  const selectAgent = useUIStore(s => s.selectAgent);
  const agents = useAgentStore(s => s.agents);
  const bp = useBreakpoint();

  if (!selectedId || !detailOpen) return null;
  const entry = agents.get(selectedId);
  if (!entry) return null;

  const { agent, fsm, tokenBreakdown, projectDir } = entry;
  const color = CLI_PALETTES[agent.cli_type]?.badge ?? '#666';
  const cliBadgeLetter = agent.cli_type === 'claude' ? 'C' : agent.cli_type === 'codex' ? 'X' : 'G';
  const cliLabel = agent.cli_type === 'claude' ? 'Claude Code' : agent.cli_type === 'codex' ? 'Codex CLI' : 'Gemini CLI';

  const style = bp === 'mobile' ? mobileSheetStyle : bp === 'tablet' ? tabletPanelStyle : panelStyle;

  return (
    <div style={style}>
      {/* Close button */}
      <button onClick={() => selectAgent(null)} style={closeBtn}>
        ✕
      </button>

      {/* Header: CLI badge + name */}
      <div style={headerStyle}>
        <span style={{ ...badgeStyle, backgroundColor: color }}>
          {cliBadgeLetter}
        </span>
        <div style={{ minWidth: 0 }}>
          <div style={{ color: '#E0E0E0', fontSize: 14, fontWeight: 'bold', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {agent.display_name}
          </div>
          <div style={{ color: '#888', fontSize: 10 }}>
            {cliLabel} &middot; {agent.session_id?.slice(0, 8) ?? agent.id.slice(0, 8)}
          </div>
        </div>
      </div>

      <Divider />

      {/* Status */}
      <Section title="Status">
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{
            display: 'inline-block',
            width: 8,
            height: 8,
            borderRadius: '50%',
            backgroundColor: statusColor(agent.status),
            flexShrink: 0,
          }} />
          <span style={{ color: '#E0E0E0', fontSize: 12 }}>
            {statusLabel(agent.status, fsm.state)}
          </span>
        </div>
        {agent.current_tool && (
          <div style={{ color: '#AAA', fontSize: 11, marginTop: 4 }}>
            {agent.current_tool}
            {agent.tool_detail ? ` \u2014 ${truncate(agent.tool_detail, 40)}` : ''}
          </div>
        )}
      </Section>

      <Divider />

      {/* Tokens */}
      <Section title="Token Usage">
        <TokenRow label="Input" value={tokenBreakdown.input} />
        <TokenRow label="Output" value={tokenBreakdown.output} />
        <TokenRow label="Cached" value={tokenBreakdown.cached} />
        <TokenRow label="Total" value={agent.tokens_total} bold />
      </Section>

      {/* Sub-agents */}
      {fsm.subAgents.length > 0 && (
        <>
          <Divider />
          <Section title={`Sub-Agents (${fsm.subAgents.length})`}>
            {fsm.subAgents.map(sub => (
              <div key={sub.id} style={{ color: '#AAA', fontSize: 11, marginBottom: 2 }}>
                {sub.label}
              </div>
            ))}
          </Section>
        </>
      )}

      {/* Project */}
      {projectDir && (
        <>
          <Divider />
          <Section title="Project">
            <div style={{ color: '#AAA', fontSize: 10, wordBreak: 'break-all' }}>
              {projectDir}
            </div>
          </Section>
        </>
      )}
    </div>
  );
}
