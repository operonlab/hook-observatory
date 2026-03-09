import { useEffect, useRef } from 'react'
import { useMethodStore } from '../stores/methodStore'

export function useRecurringItems() {
  const {
    recurringItems,
    recurringLoading,
    fetchRecurringItems,
    addRecurringItem,
    updateRecurringItem,
    removeRecurringItem,
  } = useMethodStore()

  const fetched = useRef(false)
  useEffect(() => {
    if (!fetched.current) {
      fetched.current = true
      fetchRecurringItems()
    }
  }, [fetchRecurringItems])

  return {
    items: recurringItems,
    loading: recurringLoading,
    add: addRecurringItem,
    update: updateRecurringItem,
    remove: removeRecurringItem,
    refresh: fetchRecurringItems,
  }
}
