/**
 * Standardized error handler for Zustand store catch blocks.
 * Replaces 37+ instances of: set({ error: err instanceof Error ? err.message : 'Failed to X' })
 */
export function handleStoreError(
  set: (partial: { error: string | null }) => void,
  err: unknown,
  fallbackMessage: string,
) {
  set({ error: err instanceof Error ? err.message : fallbackMessage })
}
