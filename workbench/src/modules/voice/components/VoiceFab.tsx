import { Mic, MicOff } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useVoiceGateway } from '../hooks/useVoiceGateway'
import { useVoiceStore } from '../stores/voiceStore'

const STATE_COLORS: Record<string, string> = {
  IDLE: '#666',
  LISTENING: '#f59e0b',
  PROCESSING: '#3b82f6',
  RESPONDING: '#10b981',
}

/**
 * Floating microphone button for voice gateway.
 * Shows current state via color indicator.
 * Placed in AppHeader next to CaptureBadge.
 */
export default function VoiceFab() {
  const { state, enabled, connected, transcripts } = useVoiceStore()
  const { enable, disable } = useVoiceGateway()
  const [showTooltip, setShowTooltip] = useState(false)
  const [lastTranscript, setLastTranscript] = useState('')

  const toggle = useCallback(() => {
    if (enabled) {
      disable()
    } else {
      enable()
    }
  }, [enabled, enable, disable])

  // Flash last transcript briefly
  useEffect(() => {
    if (transcripts.length > 0) {
      setLastTranscript(transcripts[0].text)
      setShowTooltip(true)
      const timer = setTimeout(() => setShowTooltip(false), 3000)
      return () => clearTimeout(timer)
    }
  }, [transcripts])

  const stateColor = enabled && connected ? STATE_COLORS[state] || '#666' : '#444'
  const isActive = enabled && state !== 'IDLE'

  return (
    <div style={{ position: 'relative' }}>
      <button
        type="button"
        onClick={toggle}
        onMouseEnter={() => setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: 28,
          height: 28,
          borderRadius: 6,
          border: 'none',
          background: enabled ? `${stateColor}18` : 'transparent',
          color: stateColor,
          cursor: 'pointer',
          transition: 'all 0.2s',
          position: 'relative',
        }}
        aria-label={enabled ? 'Disable voice' : 'Enable voice'}
      >
        {enabled ? <Mic size={16} /> : <MicOff size={16} />}

        {/* Pulsing indicator when active */}
        {isActive && (
          <span
            style={{
              position: 'absolute',
              top: 2,
              right: 2,
              width: 6,
              height: 6,
              borderRadius: '50%',
              background: stateColor,
              animation: 'voice-pulse 1.5s ease-in-out infinite',
            }}
          />
        )}
      </button>

      {/* Tooltip / last transcript */}
      {showTooltip && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            right: 0,
            marginTop: 8,
            padding: '6px 10px',
            background: '#1a1a2e',
            border: '1px solid #333',
            borderRadius: 6,
            fontSize: 12,
            color: '#ccc',
            whiteSpace: 'nowrap',
            maxWidth: 240,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            zIndex: 100,
          }}
        >
          {lastTranscript || (enabled ? `Voice: ${state}` : 'Voice: OFF')}
        </div>
      )}

      <style>{`
        @keyframes voice-pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.5; transform: scale(1.3); }
        }
      `}</style>
    </div>
  )
}
