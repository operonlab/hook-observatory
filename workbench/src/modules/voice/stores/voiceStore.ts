import { create } from 'zustand'
import { devtools } from 'zustand/middleware'
import { withJournal } from '@/shared/utils/journalMiddleware'
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

export const useVoiceStore = create<VoiceStore>()(
  devtools(
    withJournal((set) => ({
      state: 'IDLE',
      mode: 'server',
      enabled: false,
      connected: false,
      transcripts: [],
      config: null,

      setState: (state) => set({ state }, false, 'voice/setState'),
      setMode: (mode) => set({ mode }, false, 'voice/setMode'),
      setEnabled: (enabled) => set({ enabled }, false, 'voice/setEnabled'),
      setConnected: (connected) => set({ connected }, false, 'voice/setConnected'),
      addTranscript: (entry) =>
        set(
          (s) => ({
            transcripts: [entry, ...s.transcripts].slice(0, 50),
          }),
          false,
          'voice/addTranscript',
        ),
      setConfig: (config) => set({ config }, false, 'voice/setConfig'),
      clearTranscripts: () => set({ transcripts: [] }, false, 'voice/clearTranscripts'),

      handleEvent: (event) =>
        set(
          (s) => {
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
          },
          false,
          'voice/handleEvent',
        ),
    })),
    { name: 'voiceStore' },
  ),
)
