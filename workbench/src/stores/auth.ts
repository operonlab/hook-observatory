import { create } from 'zustand'
import { devtools } from 'zustand/middleware'
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
    (set) => ({
      user: null,
      loading: false,
      initialized: false,

      login: async (email, password) => {
        set({ loading: true })
        try {
          const data = await gateway.login(email, password)
          set({ user: data.user, loading: false })
        } catch (err) {
          set({ loading: false })
          throw err
        }
      },

      register: async (email, password, name) => {
        set({ loading: true })
        try {
          const data = await gateway.register(email, password, name)
          set({ user: data.user, loading: false })
        } catch (err) {
          set({ loading: false })
          throw err
        }
      },

      logout: async () => {
        set({ loading: true })
        try {
          await gateway.logout()
          set({ user: null, loading: false })
        } catch {
          set({ loading: false })
        }
      },

      checkSession: async () => {
        set({ loading: true })
        try {
          const data = await gateway.getSession()
          set({ user: data.user, loading: false, initialized: true })
        } catch {
          set({ user: null, loading: false, initialized: true })
        }
      },
    }),
    { name: 'authStore' },
  ),
)
