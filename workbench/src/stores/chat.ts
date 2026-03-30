import { create } from 'zustand'
import { devtools } from 'zustand/middleware'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: number
  module?: string
}

interface ChatState {
  open: boolean
  messages: ChatMessage[]
  currentModule: string | null

  toggle: () => void
  setOpen: (v: boolean) => void
  setCurrentModule: (m: string | null) => void
  addMessage: (msg: Omit<ChatMessage, 'id' | 'timestamp'>) => void
  clearMessages: () => void
}

let msgCounter = 0

export const useChatStore = create<ChatState>()(
  devtools(
    (set, _get) => ({
      open: false,
      messages: [],
      currentModule: null,

      toggle: () => set((s) => ({ open: !s.open })),
      setOpen: (v) => set({ open: v }),
      setCurrentModule: (m) => set({ currentModule: m }),

      addMessage: (msg) => {
        const id = `msg-${Date.now()}-${++msgCounter}`
        set((s) => ({
          messages: [...s.messages, { ...msg, id, timestamp: Date.now() }],
        }))
      },

      clearMessages: () => set({ messages: [] }),
    }),
    { name: 'chatStore' },
  ),
)
