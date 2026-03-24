export type VoiceState = 'IDLE' | 'LISTENING' | 'PROCESSING' | 'RESPONDING'
export type VoiceMode = 'server' | 'client' | 'standby'
export type SourcePath = 'client' | 'server'

export interface VoiceEvent {
  type: string
  source_path?: SourcePath
  ts?: number
  [key: string]: unknown
}

export interface VoiceStatus {
  state: VoiceState
  time_in_state_s: number
  transitions: number
  active_mode: VoiceMode
  client_connected: boolean
  server_enabled: boolean
  events_published: number
  pipeline_active: boolean
}

export interface VoiceClientConfig {
  language: string
  keywords: string[]
  sensitivity: number
  client: {
    whisper_model: string
    webgpu_preferred: boolean
  }
}

export interface TranscriptEntry {
  text: string
  timestamp: number
  source_path: SourcePath
  engine?: string
}
