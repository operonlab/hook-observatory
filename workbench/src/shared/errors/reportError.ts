/**
 * Report frontend errors to Core /api/_diagnostics/client-error endpoint
 * so they land in /opt/homebrew/var/log/workshop/core/client-errors.log
 * with the same JSON schema as backend logs.
 */

export interface ClientErrorPayload {
  message: string
  stack?: string
  url: string
  user_agent: string
  request_id?: string
  context?: Record<string, unknown>
}

let queued: ClientErrorPayload[] = []
let flushTimer: ReturnType<typeof window.setTimeout> | null = null

export function reportError(error: Error | unknown, context?: Record<string, unknown>): void {
  const err = error instanceof Error ? error : new Error(String(error))
  const payload: ClientErrorPayload = {
    message: err.message,
    stack: err.stack,
    url: window.location.href,
    user_agent: navigator.userAgent,
    request_id: (window as { __workshopRequestId?: string }).__workshopRequestId,
    context,
  }
  queued.push(payload)
  scheduleFlush()
}

function scheduleFlush(): void {
  if (flushTimer != null) return
  flushTimer = window.setTimeout(flush, 500)
}

async function flush(): Promise<void> {
  flushTimer = null
  const batch = queued.splice(0)
  if (batch.length === 0) return
  try {
    await fetch('/api/_diagnostics/client-error', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ errors: batch }),
      // best-effort, don't block UI
      keepalive: true,
    })
  } catch {
    // If endpoint fails, drop silently — we don't want a loop
  }
}

// Install global handlers (side-effect on import)
if (typeof window !== 'undefined') {
  window.addEventListener('error', (e) =>
    reportError(e.error ?? e.message, { type: 'window.error' }),
  )
  window.addEventListener('unhandledrejection', (e) =>
    reportError(e.reason, { type: 'unhandled_rejection' }),
  )
}
