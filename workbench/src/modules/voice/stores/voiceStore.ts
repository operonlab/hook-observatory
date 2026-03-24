import { create } from 'zustand'
import type {
  TranscriptEntry,
  VoiceClientConfig,
  VoiceEvent,
  VoiceMode,
  VoiceState,
} from '../types'

interface VoiceStore {
  // State
  state: VoiceState
  mode: VoiceMode
  enabled: boolean
  connected: boolean
  transcripts: TranscriptEntry[]
  config: VoiceClientConfig | null

  // Actions
  setState: (state: VoiceState) => void
  setMode: (mode: VoiceMode) => void
  setEnabled: (enabled: boolean) => void
  setConnected: (connected: boolean) => void
  addTranscript: (entry: TranscriptEntry) => void
  setConfig: (config: VoiceClientConfig) => void
  handleEvent: (event: VoiceEvent) => void
  clearTranscripts: () => void
}

export const useVoiceStore = create<VoiceStore>((set) => ({
  state: 'IDLE',
  mode: 'server',
  enabled: false,
  connected: false,
  transcripts: [],
  config: null,

  setState: (state) => set({ state }),
  setMode: (mode) => set({ mode }),
  setEnabled: (enabled) => set({ enabled }),
  setConnected: (connected) => set({ connected }),
  addTranscript: (entry) =>
    set((s) => ({
      transcripts: [entry, ...s.transcripts].slice(0, 50),
    })),
  setConfig: (config) => set({ config }),
  clearTranscripts: () => set({ transcripts: [] }),

  handleEvent: (event) =>
    set((s) => {
      const updates: Partial<VoiceStore> = {}

      switch (event.type) {
        case 'voice.state.changed':
          updates.state = (event.to as VoiceState) || s.state
          break
        case 'voice.mode.switched':
          updates.mode = (event.current as VoiceMode) || s.mode
          break
        case 'voice.transcript.completed':
          if (typeof event.text === 'string' && event.text) {
            updates.transcripts = [
              {
                text: event.text,
                timestamp: Date.now(),
                source_path: (event.source_path as 'client' | 'server') || 'server',
                engine: event.engine as string | undefined,
              },
              ...s.transcripts,
            ].slice(0, 50)
          }
          break
      }

      return updates
    }),
}))
