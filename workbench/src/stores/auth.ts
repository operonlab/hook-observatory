import { create } from 'zustand'
import { devtools } from 'zustand/middleware'
import { withJournal } from '@/shared/utils/journalMiddleware'
import * as gateway from '@/api/gateway'
import type { User } from '@/types'

interface AuthState {
  user: User | null
  loading: boolean
  initialized: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, name: string) => Promise<void>
  logout: () => Promise<void>
  checkSession: () => Promise<void>
}

export const useAuthStore = create<AuthState>()(
  devtools(
    withJournal((set) => ({
      user: null,
      loading: false,
      initialized: false,

      login: async (email, password) => {
        set({ loading: true }, false, 'auth/loginStart')
        try {
          const data = await gateway.login(email, password)
          set({ user: data.user, loading: false }, false, 'auth/loginSuccess')
        } catch (err) {
          set({ loading: false }, false, 'auth/loginError')
          throw err
        }
      },

      register: async (email, password, name) => {
        set({ loading: true }, false, 'auth/registerStart')
        try {
          const data = await gateway.register(email, password, name)
          set({ user: data.user, loading: false }, false, 'auth/registerSuccess')
        } catch (err) {
          set({ loading: false }, false, 'auth/registerError')
          throw err
        }
      },

      logout: async () => {
        set({ loading: true }, false, 'auth/logoutStart')
        try {
          await gateway.logout()
          set({ user: null, loading: false }, false, 'auth/logoutSuccess')
        } catch {
          set({ loading: false }, false, 'auth/logoutError')
        }
      },

      checkSession: async () => {
        set({ loading: true }, false, 'auth/checkSessionStart')
        try {
          const data = await gateway.getSession()
          set({ user: data.user, loading: false, initialized: true }, false, 'auth/checkSessionSuccess')
        } catch {
          set({ user: null, loading: false, initialized: true }, false, 'auth/checkSessionError')
        }
      },
    })),
    { name: 'authStore' },
  ),
)
