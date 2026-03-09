import { useEffect, useRef } from 'react'
import { useMethodStore } from '../stores/methodStore'

export function useActiveMethod() {
  const {
    activeSelections,
    primaryMethod,
    layoutType,
    compositeConfig,
    loading,
    error,
    fetchActiveMethod,
  } = useMethodStore()

  const fetched = useRef(false)
  useEffect(() => {
    if (!fetched.current) {
      fetched.current = true
      fetchActiveMethod()
    }
  }, [fetchActiveMethod])

  return {
    selections: activeSelections,
    method: primaryMethod,
    layoutType,
    config: compositeConfig,
    loading,
    error,
    refresh: fetchActiveMethod,
  }
}
