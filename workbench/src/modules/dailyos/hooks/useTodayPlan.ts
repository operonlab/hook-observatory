import { useEffect } from 'react'
import { useMethodStore } from '../stores/methodStore'

export function useTodayPlan() {
  const {
    todayPlan,
    planItems,
    loading,
    toggleItem,
    transitionPlan,
    updatePlanItems,
    fetchTodayPlan,
  } = useMethodStore()

  useEffect(() => {
    if (!todayPlan) {
      fetchTodayPlan()
    }
  }, [todayPlan, fetchTodayPlan])

  return {
    plan: todayPlan,
    items: planItems,
    loading: loading && !todayPlan,
    toggleItem,
    transitionPlan,
    updatePlanItems,
  }
}
