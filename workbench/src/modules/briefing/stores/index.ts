import { create } from 'zustand'
import { devtools, persist } from 'zustand/middleware'
import { withJournal } from '@/shared/utils/journalMiddleware'

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
    withJournal(
      persist(
        (set) => ({
          activePage: 'today',
          selectedDate: todayStr(),
          briefingsPage: 1,

          setActivePage: (page) => set({ activePage: page }, false, 'briefing/setActivePage'),
          setSelectedDate: (date) => set({ selectedDate: date }, false, 'briefing/setSelectedDate'),
          setBriefingsPage: (page) =>
            set({ briefingsPage: page }, false, 'briefing/setBriefingsPage'),
        }),
        {
          name: 'briefing-cache',
          partialize: (state) => ({
            selectedDate: state.selectedDate,
          }),
        },
      ),
    ),
    { name: 'briefingStore' },
  ),
)
