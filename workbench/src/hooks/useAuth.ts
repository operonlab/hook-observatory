import { useShallow } from 'zustand/react/shallow'
import { useAuthStore } from '@/stores/auth'

export function useAuth() {
  const { user, loading, initialized, login, register, logout, checkSession } = useAuthStore(
    useShallow((s) => ({
      user: s.user,
      loading: s.loading,
      initialized: s.initialized,
      login: s.login,
      register: s.register,
      logout: s.logout,
      checkSession: s.checkSession,
    })),
  )

  return {
    user,
    loading,
    initialized,
    isAuthenticated: !!user,
    login,
    register,
    logout,
    checkSession,
  }
}
