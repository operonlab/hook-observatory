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
  {
    id: 'fsm-dashboard',
    name: '狀態機儀表板',
    description: 'FSM 狀態圖視覺化、轉換模擬器、全域狀態機總覽',
    icon: '🔄',
    color: '#a29bfe',
    url: '/fsm-dashboard.html',
  },
  {
    id: 'sean-analysis',
    name: '人物情報分析',
    description: '機密人物情報分析報告',
    icon: '🕵️',
    color: '#f38ba8',
    url: '/static/sean-analysis/',
  },
  {
    id: 'pwa-debug',
    name: 'PWA Debug',
    description: 'Service Worker、manifest、PWA 安裝狀態診斷',
    icon: '🔧',
    color: '#f9e2af',
    url: '/pwa-debug.html',
  },
  {
    id: 'tools-index',
    name: '靜態工具索引',
    description: 'Workshop 靜態工具集合總覽頁',
    icon: '📇',
    color: '#94e2d5',
    url: '/tools/',
  },
]
