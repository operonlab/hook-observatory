import { useEffect } from 'react'
import { useMethodStore } from '../stores/methodStore'

export function useActiveMethod() {
  const {
    activeMethod,
    activeSelection,
    effectiveConfig,
    loading,
    error,
    fetchActiveMethod,
  } = useMethodStore()

  useEffect(() => {
    if (!activeSelection) {
      fetchActiveMethod()
    }
  }, [activeSelection, fetchActiveMethod])

  return {
    method: activeMethod,
    selection: activeSelection,
    config: effectiveConfig,
    loading: loading && !activeMethod,
    error,
  }
}
