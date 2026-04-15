export interface ToolEntry {
  id: string
  name: string
  description: string
  icon: string
  color: string
  url: string
}

export const TOOL_LIST: ToolEntry[] = [
  {
    id: 'srt-fixer',
    name: 'SRT 字幕修正',
    description: 'SRT 批次修正 — 時間重疊、異常偵測、格式修復',
    icon: '✂️',
    color: '#6c8aff',
    url: '/tools/srt-fixer/',
  },
  {
    id: 'memvault-techstack',
    name: 'Memvault 技術全景',
    description: 'Memvault 記憶引擎架構視覺化、pipeline operators 全景圖',
    icon: '🗺️',
    color: '#cba6f7',
    url: '/tools/memvault-techstack/',
  },
]
