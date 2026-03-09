import { useEffect, useRef } from 'react'
import { useMethodStore } from '../stores/methodStore'

export function useTodayPlan() {
  const {
    todayPlan,
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
    fetchTodayPlan,
  } = useMethodStore()

  const fetched = useRef(false)
  useEffect(() => {
    if (!fetched.current) {
      fetched.current = true
      fetchTodayPlan()
    }
  }, [fetchTodayPlan])

  return {
    plan: todayPlan,
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
    refresh: fetchTodayPlan,
  }
}
