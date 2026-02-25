// Timeline replay control bar (C6) — fixed at bottom of screen

import { useEffect } from 'react';
import { useTimelineStore } from '../stores/timelineStore';
import { timelineRecorder } from '../engine/TimelineRecorder';

export default function TimelineBar() {
  const replaying = useTimelineStore(s => s.replaying);
  const currentIndex = useTimelineStore(s => s.currentIndex);
  const frameCount = useTimelineStore(s => s.frameCount);
  const paused = useTimelineStore(s => s.paused);
  const speed = useTimelineStore(s => s.speed);
  const startReplay = useTimelineStore(s => s.startReplay);
  const stopReplay = useTimelineStore(s => s.stopReplay);
  const togglePause = useTimelineStore(s => s.togglePause);
  const setSpeed = useTimelineStore(s => s.setSpeed);
  const seekTo = useTimelineStore(s => s.seekTo);
  const tick = useTimelineStore(s => s.tick);
  const updateFrameCount = useTimelineStore(s => s.updateFrameCount);

  // Update frame count periodically (when not replaying)
  useEffect(() => {
    if (replaying) return;
    const timer = setInterval(updateFrameCount, 5000);
    updateFrameCount();
    return () => clearInterval(timer);
  }, [replaying, updateFrameCount]);

  // Replay tick
  useEffect(() => {
    if (!replaying || paused) return;
    // Tick at ~200ms intervals (5fps scrub speed)
    const timer = setInterval(tick, 200);
    return () => clearInterval(timer);
  }, [replaying, paused, tick]);

  // Format timestamp
  const formatTime = (index: number): string => {
    const frame = timelineRecorder.getFrame(index);
    if (!frame) return '--:--';
    const d = new Date(frame.timestamp);
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`;
  };

  const currentFrame = timelineRecorder.getFrame(currentIndex);
  const agentCount = currentFrame?.agents.length ?? 0;

  if (!replaying) {
    // Compact button when not replaying
    const totalFrames = frameCount;
    if (totalFrames < 2) return null; // not enough data

    const range = timelineRecorder.getTimeRange();
    const durationMin = range ? Math.round((range.end - range.start) / 60000) : 0;

    return (
      <button
        onClick={startReplay}
        style={startBtnStyle}
        title={`${totalFrames} 幀，約 ${durationMin} 分鐘`}
      >
        {'▶ 回放'} ({durationMin}m)
      </button>
    );
  }

  // Full timeline bar when replaying
  return (
    <div style={barStyle}>
      <button onClick={stopReplay} style={controlBtn} title="停止回放">
        {'■'}
      </button>
      <button onClick={togglePause} style={controlBtn} title={paused ? '播放' : '暫停'}>
        {paused ? '▶' : '❚❚'}
      </button>

      <span style={{ fontSize: 10, color: '#AAA', minWidth: 55, textAlign: 'center' }}>
        {formatTime(currentIndex)}
      </span>

      <input
        type="range"
        min={0}
        max={Math.max(0, frameCount - 1)}
        value={currentIndex}
        onChange={e => seekTo(Number(e.target.value))}
        style={sliderStyle}
      />

      <span style={{ fontSize: 10, color: '#666', minWidth: 40, textAlign: 'right' }}>
        {currentIndex + 1}/{frameCount}
      </span>

      <span style={{ fontSize: 10, color: '#888', marginLeft: 8 }}>
        {agentCount} 個代理
      </span>

      {/* Speed control */}
      <div style={{ marginLeft: 8, display: 'flex', gap: 2 }}>
        {[0.5, 1, 2, 4].map(s => (
          <button
            key={s}
            onClick={() => setSpeed(s)}
            style={{
              ...speedBtn,
              color: speed === s ? '#4A90D9' : '#666',
              borderColor: speed === s ? '#4A90D9' : '#444',
            }}
          >
            {s}x
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Styles ──

const barStyle: React.CSSProperties = {
  position: 'fixed',
  bottom: 0,
  left: 0,
  right: 0,
  height: 36,
  display: 'flex',
  alignItems: 'center',
  padding: '0 12px',
  gap: 6,
  background: 'rgba(15, 15, 25, 0.95)',
  borderTop: '1px solid #333',
  fontFamily: 'monospace',
  zIndex: 20,
};

const controlBtn: React.CSSProperties = {
  background: 'none',
  border: '1px solid #555',
  borderRadius: 4,
  color: '#CCC',
  fontSize: 12,
  width: 28,
  height: 24,
  cursor: 'pointer',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
};

const sliderStyle: React.CSSProperties = {
  flex: 1,
  height: 4,
  appearance: 'auto',
  accentColor: '#4A90D9',
  cursor: 'pointer',
};

const speedBtn: React.CSSProperties = {
  background: 'none',
  border: '1px solid #444',
  borderRadius: 3,
  fontSize: 9,
  padding: '2px 4px',
  cursor: 'pointer',
  fontFamily: 'monospace',
};

const startBtnStyle: React.CSSProperties = {
  position: 'fixed',
  bottom: 12,
  left: '50%',
  transform: 'translateX(-50%)',
  background: 'rgba(20, 20, 35, 0.9)',
  border: '1px solid #555',
  borderRadius: 6,
  color: '#AAA',
  fontSize: 11,
  padding: '4px 12px',
  cursor: 'pointer',
  fontFamily: 'monospace',
  zIndex: 15,
};
