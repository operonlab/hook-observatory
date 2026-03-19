import type { StateCreator } from 'zustand'

/** Common async state shape for list-fetching slices. */
export interface AsyncSlice<T> {
  items: T[]
  loading: boolean
  error: string | null
  fetch: (...args: unknown[]) => Promise<void>
  reset: () => void
}

/**
 * Factory for a Zustand slice that manages async list fetching.
 *
 * Usage:
 * ```ts
 * interface MyStore extends AsyncSlice<Item> { extra: string }
 * const useStore = create<MyStore>()((...a) => ({
 *   ...createAsyncSlice<Item>(api.listItems)(...a),
 *   extra: '',
 * }))
 * ```
 */
export function createAsyncSlice<T>(
  fetcher: (...args: unknown[]) => Promise<T[]>,
): StateCreator<AsyncSlice<T>> {
  return (set) => ({
    items: [],
    loading: false,
    error: null,
    fetch: async (...args: unknown[]) => {
      set({ loading: true, error: null })
      try {
        const items = await fetcher(...args)
        set({ items, loading: false })
      } catch (e) {
        set({ error: e instanceof Error ? e.message : String(e), loading: false })
      }
    },
    reset: () => set({ items: [], loading: false, error: null }),
  })
}
