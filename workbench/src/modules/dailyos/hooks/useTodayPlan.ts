import { useEffect, useRef } from 'react'
import { useMethodStore } from '../stores/methodStore'

/**
 * Hook to load a plan for a specific date.
 * Defaults to today when no date is provided.
 */
export function useDatePlan(date?: string) {
  const {
    currentDate,
    currentPlan,
    planItems,
    planLoading,
    addItem,
    removeItem,
    editItem,
    reorderItem,
    reorderItems,
    toggleItem,
    assignCategory,
    scheduleItem,
    moveRight,
    moveLeft,
    transitionPlan,
    completeReview,
    updatePlanItems,
    fetchPlan,
  } = useMethodStore()

  const lastDate = useRef<string | undefined>(undefined)
  useEffect(() => {
    if (lastDate.current !== date) {
      lastDate.current = date
      fetchPlan(date)
    }
  }, [date, fetchPlan])

  return {
    plan: currentPlan,
    currentDate,
    items: planItems,
    loading: planLoading,
    addItem,
    removeItem,
    editItem,
    reorderItem,
    reorderItems,
    toggleItem,
    assignCategory,
    scheduleItem,
    moveRight,
    moveLeft,
    transitionPlan,
    completeReview,
    updatePlanItems,
    refresh: () => fetchPlan(date),
  }
}

/** Backward-compatible wrapper: loads today's plan. */
export function useTodayPlan() {
  return useDatePlan()
}
