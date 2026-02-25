// 儀表板側欄 — 工作階段列表、Token 統計、編輯切換

import { useState } from 'react';
import { useAgentStore } from '../stores/agentStore';
import { useWSStore } from '../stores/wsStore';
import { useOfficeStore } from '../stores/officeStore';
import { useResourceStore } from '../stores/resourceStore';
import { useWatchdogStore } from '../stores/watchdogStore';
import type { AlertLevel } from '../stores/watchdogStore';
import { useUIStore } from '../stores/uiStore';

const CLI_COLORS: Record<string, string> = {
  claude: '#4A90D9',
  codex: '#4CAF50',
  gemini: '#9C27B0',
};

const CLI_ICONS: Record<string, string> = {
  claude: 'C',
  codex: 'X',
  gemini: 'G',
};

const STATUS_LABELS: Record<string, string> = {
  active: '工作中',
  thinking: '思考中',
  typing: '輸入中',
  reading: '閱讀中',
  waiting: '等待中',
  idle: '閒置',
  resting: '休息中',
  offline: '離線',
  error: '錯誤',
};

const WS_LABELS: Record<string, string> = {
  connected: '已連線',
  connecting: '連線中',
  disconnected: '已斷線',
};

/** Show short label: cli_type + first 4 chars of session_id */
function shortLabel(cliType: string, sessionId?: string, agentId?: string): string {
  const suffix = (sessionId ?? agentId ?? '????').slice(0, 4);
  return `${cliType}-${suffix}`;
}

export default function Dashboard() {
  const agents = useAgentStore(s => s.agents);
  const wsStatus = useWSStore(s => s.status);
  const editMode = useOfficeStore(s => s.editMode);
  const toggleEdit = useOfficeStore(s => s.toggleEditMode);
  const saveLayout = useOfficeStore(s => s.saveLayout);
  const layoutVersion = useOfficeStore(s => s.layoutVersion);
  const layoutSaving = useOfficeStore(s => s.layoutSaving);
  const soundMuted = useUIStore(s => s.soundMuted);
  const toggleSound = useUIStore(s => s.toggleSound);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  const toggleExpand = (id: string) => {
    setExpandedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  // Separate active and resting agents
  const allAgents = [...agents.values()];
  const activeAgents = allAgents.filter(e => e.agent.status !== 'resting' && e.agent.status !== 'offline');
  const restingAgents = allAgents.filter(e => e.agent.status === 'resting');

  return (
    <div style={panelStyle}>
      <h2 style={{ fontSize: 14, margin: '0 0 8px', color: '#E0E0E0' }}>
        Agent Vista
        <button
          onClick={toggleSound}
          title={soundMuted ? '開啟音效' : '靜音'}
          style={{
            background: 'none',
            border: '1px solid #444',
            borderRadius: 4,
            color: soundMuted ? '#666' : '#E0E0E0',
            fontSize: 12,
            cursor: 'pointer',
            padding: '2px 6px',
            marginLeft: 8,
          }}
        >
          {soundMuted ? 'MUTE' : 'SND'}
        </button>
        <span style={{
          float: 'right', fontSize: 10,
          color: wsStatus === 'connected' ? '#4CAF50' : '#F44336',
        }}>
          {WS_LABELS[wsStatus] ?? wsStatus}
        </span>
      </h2>

      <div style={{ fontSize: 11, color: '#888', marginBottom: 8 }}>
        工作階段（{activeAgents.length} 活躍
        {restingAgents.length > 0 ? `・${restingAgents.length} 休息` : ''}）
      </div>

      <AgentList agents={activeAgents} expandedIds={expandedIds} toggleExpand={toggleExpand} />

      {restingAgents.length > 0 && (
        <div style={{ marginTop: 6, paddingTop: 6, borderTop: '1px solid rgba(255,255,255,0.05)' }}>
          <div style={{ fontSize: 10, color: '#666', marginBottom: 4 }}>休息室</div>
          {restingAgents.map(({ agent }) => (
            <div key={agent.id} style={{ ...agentRowStyle, opacity: 0.6 }}>
              <span style={badgeStyle(agent.cli_type)}>
                {CLI_ICONS[agent.cli_type] ?? '?'}
              </span>
              <span
                style={{ color: '#999', fontSize: 11, cursor: 'pointer' }}
                onClick={() => toggleExpand(agent.id)}
              >
                {expandedIds.has(agent.id)
                  ? `${agent.cli_type}-${agent.session_id ?? agent.id}`
                  : shortLabel(agent.cli_type, agent.session_id, agent.id)}
              </span>
              <span style={{ fontSize: 10, color: '#666', marginLeft: 4 }}>zzZ</span>
            </div>
          ))}
        </div>
      )}

      <TokenSection allAgents={allAgents} />
      <WatchdogSection />
      <ResourceSection />

      <button onClick={toggleEdit} style={btnStyle(editMode)}>
        {editMode ? '退出編輯' : '編輯佈局'}
      </button>

      {editMode && (
        <>
          <button
            onClick={() => saveLayout()}
            disabled={layoutSaving}
            style={saveBtnStyle(layoutSaving)}
          >
            {layoutSaving ? '儲存中...' : '儲存佈局'}
          </button>
          <div style={{ fontSize: 9, color: '#666', marginTop: 4, lineHeight: 1.4 }}>
            右鍵拖曳：移動 | 左鍵：選取
            <br />R：旋轉 | [ ]：寬度 | {'{ }'}：高度
            {layoutVersion > 0 && (
              <span style={{ float: 'right', color: '#555' }}>v{layoutVersion}</span>
            )}
          </div>
        </>
      )}
    </div>
  );
}

// ── Agent List with Department Grouping ──

/** Extract short project name from full path */
function projectLabel(dir: string): string {
  if (!dir) return '未知專案';
  // Take last 2 path segments for brevity: e.g. "/Users/foo/workshop/lab/agent-vista" → "lab/agent-vista"
  const parts = dir.replace(/\/+$/, '').split('/').filter(Boolean);
  if (parts.length >= 2) return parts.slice(-2).join('/');
  return parts[parts.length - 1] || dir;
}

import type { AgentEntry } from '../stores/agentStore';

function AgentList({ agents, expandedIds, toggleExpand }: {
  agents: AgentEntry[];
  expandedIds: Set<string>;
  toggleExpand: (id: string) => void;
}) {
  // Group by project directory
  const byProject = new Map<string, AgentEntry[]>();
  for (const entry of agents) {
    const key = entry.projectDir || '';
    const group = byProject.get(key) ?? [];
    group.push(entry);
    byProject.set(key, group);
  }

  // If only 1 group (or no project info), render flat
  const groups = [...byProject.entries()];
  const showGroups = groups.length > 1 || (groups.length === 1 && groups[0][0] !== '');

  return (
    <>
      {groups.map(([projDir, entries]) => (
        <div key={projDir || '_default'}>
          {showGroups && (
            <div style={{
              fontSize: 9, color: '#666', marginTop: 4, marginBottom: 2,
              borderLeft: '2px solid #4A90D9', paddingLeft: 4,
            }}>
              {projectLabel(projDir)}
              <span style={{ color: '#555', marginLeft: 4 }}>({entries.length})</span>
            </div>
          )}
          {entries.map(({ agent, fsm }) => {
            const subCount = fsm.subAgents.length;
            const expanded = expandedIds.has(agent.id);
            const label = expanded
              ? `${agent.cli_type}-${agent.session_id ?? agent.id}`
              : shortLabel(agent.cli_type, agent.session_id, agent.id);
            return (
              <div key={agent.id} style={agentRowStyle}>
                <span style={badgeStyle(agent.cli_type)}>
                  {CLI_ICONS[agent.cli_type] ?? '?'}
                </span>
                <span
                  style={{ color: '#E0E0E0', fontSize: 12, cursor: 'pointer' }}
                  onClick={() => toggleExpand(agent.id)}
                  title="點擊展開/收起完整 ID"
                >
                  {label}
                </span>
                <div style={{ fontSize: 10, color: '#888', marginLeft: 22, marginTop: 2 }}>
                  {STATUS_LABELS[agent.status] ?? agent.status}
                  {agent.current_tool ? `：${agent.current_tool}` : ''}
                </div>
                {subCount > 0 && (
                  <div style={{ fontSize: 10, color: '#666', marginLeft: 22 }}>
                    {subCount} 個子代理
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ))}
    </>
  );
}

// ── Token & Cost breakdown by CLI type ──

// Rough cost estimates per 1M tokens (blended input+output average)
const COST_PER_MTOK: Record<string, number> = {
  claude: 12,   // ~$3 input + $15 output, blended
  codex: 8,     // estimated
  gemini: 3.5,  // Gemini 2.5 Pro blended
};

interface TokenData {
  agent: { cli_type: string; tokens_total: number };
  tokenBreakdown: { input: number; output: number; cached: number };
}

function TokenSection({ allAgents }: { allAgents: TokenData[] }) {
  const totalTokens = allAgents.reduce((sum, e) => sum + e.agent.tokens_total, 0);

  // Group by CLI type: tokens + input/output breakdown
  const byCli = new Map<string, { total: number; input: number; output: number; cached: number }>();
  for (const { agent, tokenBreakdown } of allAgents) {
    const prev = byCli.get(agent.cli_type) ?? { total: 0, input: 0, output: 0, cached: 0 };
    prev.total += agent.tokens_total;
    prev.input += tokenBreakdown.input;
    prev.output += tokenBreakdown.output;
    prev.cached += tokenBreakdown.cached;
    byCli.set(agent.cli_type, prev);
  }

  // Estimate total cost
  let totalCost = 0;
  for (const [cli, data] of byCli) {
    const rate = COST_PER_MTOK[cli] ?? 5;
    totalCost += (data.total / 1_000_000) * rate;
  }

  return (
    <div style={{ borderTop: '1px solid #333', marginTop: 8, paddingTop: 8 }}>
      <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>Token 用量</div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
        <span style={{ fontSize: 13, color: '#E0E0E0' }}>
          {totalTokens.toLocaleString()}
        </span>
        {totalCost > 0 && (
          <span style={{ fontSize: 10, color: '#F9A825' }}>
            ~${totalCost.toFixed(2)}
          </span>
        )}
      </div>
      {[...byCli.entries()]
        .sort((a, b) => b[1].total - a[1].total)
        .map(([cli, data]) => {
        const cost = (data.total / 1_000_000) * (COST_PER_MTOK[cli] ?? 5);
        return (
          <div key={cli} style={{ marginBottom: 3 }}>
            <div style={{ display: 'flex', alignItems: 'center', fontSize: 10 }}>
              <span style={{
                display: 'inline-block', width: 8, height: 8, borderRadius: 2,
                backgroundColor: CLI_COLORS[cli] ?? '#666', marginRight: 5,
              }} />
              <span style={{ color: '#AAA', flex: 1 }}>{cli}</span>
              <span style={{ color: '#CCC' }}>{data.total.toLocaleString()}</span>
              {cost > 0.01 && (
                <span style={{ color: '#F9A825', marginLeft: 4, fontSize: 9 }}>
                  ${cost.toFixed(2)}
                </span>
              )}
            </div>
            {data.input > 0 && (
              <div style={{ fontSize: 9, color: '#666', marginLeft: 13 }}>
                in:{data.input.toLocaleString()} out:{data.output.toLocaleString()}
                {data.cached > 0 && ` cache:${data.cached.toLocaleString()}`}
              </div>
            )}
          </div>
        );
      })}
      {totalTokens > 0 && (
        <div style={{ display: 'flex', height: 4, borderRadius: 2, overflow: 'hidden', marginTop: 4 }}>
          {[...byCli.entries()].map(([cli, data]) => (
            <div key={cli} style={{
              flex: data.total / totalTokens,
              backgroundColor: CLI_COLORS[cli] ?? '#666',
            }} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Usage Watchdog ──

const ALERT_COLORS: Record<AlertLevel, string> = {
  normal: '#4CAF50',
  warn: '#FFC107',
  critical: '#F44336',
};

function WatchdogSection() {
  const tokPerMin = useWatchdogStore(s => s.tokensPerMinute);
  const tokPerHour = useWatchdogStore(s => s.tokensPerHour);
  const estCost = useWatchdogStore(s => s.estimatedDailyCostUSD);
  const alertLevel = useWatchdogStore(s => s.alertLevel);
  const alertMsg = useWatchdogStore(s => s.alertMessage);
  const budget = useWatchdogStore(s => s.dailyBudgetUSD);
  const setBudget = useWatchdogStore(s => s.setDailyBudget);
  const [editing, setEditing] = useState(false);
  const [budgetInput, setBudgetInput] = useState('');

  // Don't show section until we have at least some rate data
  if (tokPerMin === 0 && alertLevel === 'normal') return null;

  return (
    <div style={{ borderTop: '1px solid #333', marginTop: 8, paddingTop: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', fontSize: 11, color: '#888', marginBottom: 4 }}>
        <span style={{
          display: 'inline-block', width: 6, height: 6, borderRadius: 3,
          backgroundColor: ALERT_COLORS[alertLevel], marginRight: 5,
        }} />
        用量看門狗
      </div>

      {alertMsg && (
        <div style={{
          fontSize: 10, padding: '3px 6px', borderRadius: 3, marginBottom: 4,
          backgroundColor: alertLevel === 'critical' ? 'rgba(244,67,54,0.15)' : 'rgba(255,193,7,0.15)',
          color: ALERT_COLORS[alertLevel],
          border: `1px solid ${ALERT_COLORS[alertLevel]}33`,
        }}>
          {alertMsg}
        </div>
      )}

      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#AAA', marginBottom: 2 }}>
        <span>{Math.round(tokPerMin).toLocaleString()} tok/min</span>
        <span>{Math.round(tokPerHour).toLocaleString()} tok/hr</span>
      </div>

      {estCost > 0 && (
        <div style={{ fontSize: 10, color: '#F9A825', marginBottom: 2 }}>
          預估日花費：${estCost.toFixed(2)}
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', fontSize: 9, color: '#666', marginTop: 2 }}>
        <span>預算：</span>
        {editing ? (
          <input
            type="number"
            value={budgetInput}
            onChange={e => setBudgetInput(e.target.value)}
            onBlur={() => {
              const val = parseFloat(budgetInput);
              if (!isNaN(val) && val >= 0) setBudget(val);
              setEditing(false);
            }}
            onKeyDown={e => {
              if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
              if (e.key === 'Escape') setEditing(false);
            }}
            autoFocus
            style={{
              width: 50, fontSize: 9, background: 'rgba(255,255,255,0.1)',
              border: '1px solid #555', borderRadius: 2, color: '#CCC',
              padding: '1px 3px', marginLeft: 2, fontFamily: 'monospace',
            }}
          />
        ) : (
          <span
            onClick={() => { setBudgetInput(String(budget || '')); setEditing(true); }}
            style={{ cursor: 'pointer', color: '#999', marginLeft: 2 }}
          >
            {budget > 0 ? `$${budget}/日` : '未設定（點擊設定）'}
          </span>
        )}
      </div>

      {/* Budget progress bar */}
      {budget > 0 && estCost > 0 && (
        <div style={{
          height: 3, borderRadius: 2, overflow: 'hidden', marginTop: 4,
          background: 'rgba(255,255,255,0.05)',
        }}>
          <div style={{
            width: `${Math.min(100, (estCost / budget) * 100)}%`,
            height: '100%',
            backgroundColor: ALERT_COLORS[alertLevel],
            transition: 'width 0.5s ease',
          }} />
        </div>
      )}
    </div>
  );
}

// ── System Resource Monitor ──

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function ResourceSection() {
  const processes = useResourceStore(s => s.processes);

  if (processes.length === 0) return null;

  // Aggregate by CLI type
  const byCli = new Map<string, { cpu: number; rss: number; count: number }>();
  for (const p of processes) {
    const cli = p.cli_type ?? 'unknown';
    const agg = byCli.get(cli) ?? { cpu: 0, rss: 0, count: 0 };
    agg.cpu += p.cpu;
    agg.rss += p.rss;
    agg.count += 1;
    byCli.set(cli, agg);
  }

  const totalCpu = processes.reduce((s, p) => s + p.cpu, 0);
  const totalRss = processes.reduce((s, p) => s + p.rss, 0);

  return (
    <div style={{ borderTop: '1px solid #333', marginTop: 8, paddingTop: 8 }}>
      <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>
        系統資源（{processes.length} 程序）
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 4 }}>
        <span style={{ color: '#E0E0E0' }}>CPU {totalCpu.toFixed(1)}%</span>
        <span style={{ color: '#E0E0E0' }}>MEM {formatBytes(totalRss)}</span>
      </div>
      {[...byCli.entries()]
        .sort((a, b) => b[1].rss - a[1].rss)
        .map(([cli, agg]) => (
        <div key={cli} style={{ display: 'flex', alignItems: 'center', fontSize: 10, marginBottom: 2 }}>
          <span style={{
            display: 'inline-block', width: 8, height: 8, borderRadius: 2,
            backgroundColor: CLI_COLORS[cli] ?? '#666', marginRight: 5,
          }} />
          <span style={{ color: '#AAA', flex: 1 }}>
            {cli}
            <span style={{ color: '#666' }}> ×{agg.count}</span>
          </span>
          <span style={{ color: '#CCC', marginRight: 6 }}>{agg.cpu.toFixed(1)}%</span>
          <span style={{ color: '#CCC' }}>{formatBytes(agg.rss)}</span>
        </div>
      ))}
      {/* CPU bar */}
      {totalCpu > 0 && (
        <div style={{ display: 'flex', height: 3, borderRadius: 2, overflow: 'hidden', marginTop: 4, background: 'rgba(255,255,255,0.05)' }}>
          {[...byCli.entries()].map(([cli, agg]) => (
            <div key={cli} style={{
              width: `${Math.min(agg.cpu, 100)}%`,
              backgroundColor: CLI_COLORS[cli] ?? '#666',
              opacity: 0.8,
            }} />
          ))}
        </div>
      )}
    </div>
  );
}

function badgeStyle(cliType: string): React.CSSProperties {
  return {
    display: 'inline-block',
    width: 16, height: 16,
    lineHeight: '16px',
    textAlign: 'center',
    borderRadius: 3,
    backgroundColor: CLI_COLORS[cliType] ?? '#666',
    color: '#fff',
    fontSize: 10,
    fontWeight: 'bold',
    marginRight: 6,
  };
}

const panelStyle: React.CSSProperties = {
  position: 'fixed',
  top: 12,
  right: 12,
  width: 220,
  padding: 12,
  background: 'rgba(20, 20, 35, 0.92)',
  border: '1px solid #333',
  borderRadius: 8,
  fontFamily: 'monospace',
  zIndex: 10,
  backdropFilter: 'blur(4px)',
  maxHeight: 'calc(100vh - 24px)',
  overflowY: 'auto',
  scrollbarWidth: 'thin',
  scrollbarColor: '#2a2a40 transparent',
};

const agentRowStyle: React.CSSProperties = {
  padding: '4px 0',
  borderBottom: '1px solid rgba(255,255,255,0.05)',
};

function saveBtnStyle(saving: boolean): React.CSSProperties {
  return {
    display: 'block',
    width: '100%',
    marginTop: 4,
    padding: '5px 0',
    border: '1px solid #4A90D9',
    borderRadius: 4,
    background: saving ? 'rgba(74,144,217,0.1)' : 'rgba(74,144,217,0.2)',
    color: saving ? '#666' : '#4A90D9',
    fontFamily: 'monospace',
    fontSize: 11,
    cursor: saving ? 'default' : 'pointer',
    opacity: saving ? 0.6 : 1,
  };
}

function btnStyle(active: boolean): React.CSSProperties {
  return {
    display: 'block',
    width: '100%',
    marginTop: 8,
    padding: '6px 0',
    border: `1px solid ${active ? '#FFC832' : '#555'}`,
    borderRadius: 4,
    background: active ? 'rgba(255,200,50,0.15)' : 'transparent',
    color: active ? '#FFC832' : '#999',
    fontFamily: 'monospace',
    fontSize: 11,
    cursor: 'pointer',
  };
}
