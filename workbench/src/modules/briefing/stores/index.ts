import { create } from 'zustand'
import { devtools, persist } from 'zustand/middleware'

type NavPage = 'today' | 'history' | 'config'

interface BriefingState {
  activePage: NavPage
  selectedDate: string
  briefingsPage: number

  setActivePage: (page: NavPage) => void
  setSelectedDate: (date: string) => void
  setBriefingsPage: (page: number) => void
}

function todayStr() {
  return new Date().toISOString().slice(0, 10)
}

export const useBriefingStore = create<BriefingState>()(
  devtools(
    persist(
      (set) => ({
        activePage: 'today',
        selectedDate: todayStr(),
        briefingsPage: 1,

        setActivePage: (page) => set({ activePage: page }),
        setSelectedDate: (date) => set({ selectedDate: date }),
        setBriefingsPage: (page) => set({ briefingsPage: page }),
      }),
      {
        name: 'briefing-cache',
        partialize: (state) => ({
          selectedDate: state.selectedDate,
        }),
      },
    ),
    { name: 'briefingStore' },
  ),
)
