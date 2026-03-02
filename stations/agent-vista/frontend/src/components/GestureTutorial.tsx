// First-use gesture tutorial overlay for mobile/tablet users
// Shows once per device (localStorage), dismissed on tap or after 6s

import { useState, useEffect, useCallback } from 'react';
import { useBreakpoint } from '../hooks/useBreakpoint';

const STORAGE_KEY = 'agent-vista-gesture-tutorial-shown';

export default function GestureTutorial() {
  const bp = useBreakpoint();
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (bp === 'desktop') return;
    if (localStorage.getItem(STORAGE_KEY)) return;
    // Short delay so the office renders first
    const t = setTimeout(() => setVisible(true), 1500);
    return () => clearTimeout(t);
  }, [bp]);

  // Auto-dismiss after 6s
  useEffect(() => {
    if (!visible) return;
    const t = setTimeout(() => dismiss(), 6000);
    return () => clearTimeout(t);
  }, [visible]);

  const dismiss = useCallback(() => {
    setVisible(false);
    localStorage.setItem(STORAGE_KEY, '1');
  }, []);

  if (!visible) return null;

  return (
    <div
      onClick={dismiss}
      style={overlayStyle}
    >
      <div style={cardStyle}>
        <div style={titleStyle}>觸控操作指南</div>
        <div style={rowStyle}>
          <span style={iconStyle}>☝️</span>
          <span>單指拖曳 — 平移畫面</span>
        </div>
        <div style={rowStyle}>
          <span style={iconStyle}>🤏</span>
          <span>雙指縮放 — 放大/縮小</span>
        </div>
        <div style={rowStyle}>
          <span style={iconStyle}>👆👆</span>
          <span>雙擊 — 切換 1x/2x 倍率</span>
        </div>
        <div style={rowStyle}>
          <span style={iconStyle}>👆</span>
          <span>點擊角色 — 查看詳情</span>
        </div>
        <div style={hintStyle}>輕觸任意處關閉</div>
      </div>
    </div>
  );
}

const overlayStyle: React.CSSProperties = {
  position: 'fixed',
  inset: 0,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  background: 'rgba(0, 0, 0, 0.6)',
  zIndex: 50,
  cursor: 'pointer',
  animation: 'fadeIn 0.3s ease',
};

const cardStyle: React.CSSProperties = {
  background: 'rgba(20, 20, 35, 0.95)',
  border: '1px solid #444',
  borderRadius: 12,
  padding: '20px 24px',
  maxWidth: 280,
  fontFamily: 'monospace',
  backdropFilter: 'blur(8px)',
  boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
};

const titleStyle: React.CSSProperties = {
  color: '#FFC832',
  fontSize: 14,
  fontWeight: 'bold',
  marginBottom: 16,
  textAlign: 'center',
};

const rowStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 10,
  color: '#CCC',
  fontSize: 12,
  marginBottom: 10,
  lineHeight: '1.4',
};

const iconStyle: React.CSSProperties = {
  fontSize: 18,
  width: 28,
  textAlign: 'center',
  flexShrink: 0,
};

const hintStyle: React.CSSProperties = {
  color: '#666',
  fontSize: 10,
  textAlign: 'center',
  marginTop: 12,
};
