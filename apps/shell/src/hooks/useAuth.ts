import { useAuthStore } from "@/stores/auth";

export function useAuth() {
  const user = useAuthStore((s) => s.user);
  const loading = useAuthStore((s) => s.loading);
  const initialized = useAuthStore((s) => s.initialized);
  const login = useAuthStore((s) => s.login);
  const register = useAuthStore((s) => s.register);
  const logout = useAuthStore((s) => s.logout);
  const checkSession = useAuthStore((s) => s.checkSession);

  return {
    user,
    loading,
    initialized,
    isAuthenticated: !!user,
    login,
    register,
    logout,
    checkSession,
  };
}
