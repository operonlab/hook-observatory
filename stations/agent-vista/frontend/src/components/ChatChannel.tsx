// ChatChannel — MMO 風格聊天頻道，顯示所有 Agent 活動紀錄

import { useEffect, useRef } from 'react';
import { useChatStore } from '../stores/chatStore';
import { useBreakpoint } from '../hooks/useBreakpoint';

const CLI_COLORS: Record<string, string> = {
  claude: '#4A90D9',
  codex: '#4CAF50',
  gemini: '#9C27B0',
};

const EVENT_TYPE_COLORS: Record<string, string> = {
  session_start: '#4CAF50',
  session_end: '#F44336',
  tool_start: '#FFC832',
  tool_done: '#888',
  thinking: '#4A90D9',
  message: '#E0E0E0',
  sub_agent_start: '#FF9800',
  sub_agent_end: '#FF9800',
  tool_permission: '#FF5722',
  waiting: '#888',
};

function formatTime(ts: number): string {
  const d = new Date(ts);
  const hh = d.getHours().toString().padStart(2, '0');
  const mm = d.getMinutes().toString().padStart(2, '0');
  const ss = d.getSeconds().toString().padStart(2, '0');
  return `${hh}:${mm}:${ss}`;
}

export default function ChatChannel() {
  const messages = useChatStore(s => s.messages);
  const isOpen = useChatStore(s => s.isOpen);
  const toggle = useChatStore(s => s.toggle);
  const clear = useChatStore(s => s.clear);
  const bp = useBreakpoint();
  const isMobile = bp === 'mobile';

  const listRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new messages arrive (only when open)
  useEffect(() => {
    if (isOpen && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages, isOpen]);

  const lastMsg = messages.length > 0 ? messages[messages.length - 1] : null;

  return (
    <div style={containerStyle(isOpen, isMobile)}>
      {/* Header bar — always visible */}
      <div style={headerStyle} onClick={toggle}>
        <span style={{ color: '#FFC832', fontSize: 11 }}>
          聊天頻道
        </span>
        <span style={{ color: '#888', fontSize: 10, marginLeft: 6 }}>
          ({messages.length})
        </span>

        {/* Last message preview — only when collapsed */}
        {!isOpen && lastMsg && (
          <span style={previewStyle}>
            <span style={{ color: CLI_COLORS[lastMsg.cliType] ?? '#888' }}>
              [{lastMsg.agentName}]
            </span>
            {' '}
            <span style={{ color: '#aaa' }}>{lastMsg.text}</span>
          </span>
        )}

        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
          {isOpen && (
            <button
              onClick={(e) => { e.stopPropagation(); clear(); }}
              style={clearBtnStyle}
              title="清除紀錄"
            >
              清除
            </button>
          )}
          <span style={{ color: '#888', fontSize: 11 }}>
            {isOpen ? '▼' : '▲'}
          </span>
        </div>
      </div>

      {/* Message list — visible when open */}
      {isOpen && (
        <div ref={listRef} style={messageListStyle}>
          {messages.length === 0 ? (
            <div style={{ color: '#555', fontSize: isMobile ? 10 : 11, textAlign: 'center', padding: '16px 0' }}>
              尚無活動紀錄
            </div>
          ) : (
            messages.map((msg) => (
              <div key={msg.id} style={isMobile ? mobileMessageRowStyle : messageRowStyle}>
                <span style={{ color: '#555', minWidth: 64 }}>
                  {formatTime(msg.timestamp)}
                </span>
                <span style={{
                  color: CLI_COLORS[msg.cliType] ?? '#888',
                  minWidth: 100,
                  fontWeight: 'bold',
                }}>
                  [{msg.agentName}]
                </span>
                <span style={{ color: EVENT_TYPE_COLORS[msg.eventType] ?? '#aaa', flex: 1, minWidth: 0, wordBreak: 'break-word' }}>
                  {msg.text}
                </span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

function containerStyle(isOpen: boolean, isMobile = false): React.CSSProperties {
  return {
    position: 'fixed',
    bottom: isMobile ? 40 : 0,
    left: '50%',
    transform: 'translateX(-50%)',
    width: isMobile ? '100vw' : 'min(900px, 100vw)',
    background: 'rgba(14, 14, 24, 0.93)',
    border: '1px solid #2a2a40',
    borderBottom: 'none',
    borderRadius: '8px 8px 0 0',
    fontFamily: 'monospace',
    zIndex: 20,
    backdropFilter: 'blur(4px)',
    transition: 'height 0.2s ease',
    overflow: 'hidden',
    height: isOpen ? 'auto' : 32,
  };
}

const headerStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  padding: '6px 12px',
  cursor: 'pointer',
  borderBottom: '1px solid #2a2a40',
  height: 32,
  boxSizing: 'border-box',
  userSelect: 'none',
};

const previewStyle: React.CSSProperties = {
  marginLeft: 16,
  fontSize: 11,
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
  maxWidth: 500,
  flex: 1,
};

const messageListStyle: React.CSSProperties = {
  maxHeight: 200,
  overflowY: 'auto',
  padding: '4px 0',
  scrollbarWidth: 'thin',
  scrollbarColor: '#2a2a40 transparent',
};

const messageRowStyle: React.CSSProperties = {
  display: 'flex',
  gap: 8,
  padding: '3px 12px',
  fontSize: 11,
  lineHeight: '18px',
  borderBottom: '1px solid rgba(255,255,255,0.03)',
  flexWrap: 'wrap',
};

const mobileMessageRowStyle: React.CSSProperties = {
  ...messageRowStyle,
  gap: 4,
  padding: '2px 8px',
  fontSize: 10,
  lineHeight: '16px',
};

const clearBtnStyle: React.CSSProperties = {
  fontSize: 10,
  padding: '2px 6px',
  background: 'transparent',
  border: '1px solid #444',
  borderRadius: 3,
  color: '#888',
  cursor: 'pointer',
  fontFamily: 'monospace',
};
