/** Extract error message from unknown catch value. */
export const handleError = (err: unknown): string =>
  err instanceof Error ? err.message : 'Unknown error'
