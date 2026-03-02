import { useCallback, useEffect, useState } from 'react'
import { useSwipeGesture } from '@/modules/dashboard/hooks/useSwipeGesture'
import Home from '@/pages/Home'

const DashboardCanvas = React.lazy(() => import('@/modules/dashboard/components/DashboardCanvas'))

import React from 'react'

export default function AppsPage() {
  const [panel, setPanel] = useState(0)

  // Listen for toggle-dashboard custom event from AppHeader
  useEffect(() => {
    function handler() {
      setPanel((p) => (p === 0 ? 1 : 0))
    }
    window.addEventListener('toggle-dashboard', handler)
    return () => window.removeEventListener('toggle-dashboard', handler)
  }, [])

  const goToDashboard = useCallback(() => setPanel(1), [])
  const goToHome = useCallback(() => setPanel(0), [])

  const swipeHandlers = useSwipeGesture({
    onSwipeLeft: goToDashboard,
    onSwipeRight: goToHome,
  })

  return (
    <div className="relative h-full overflow-hidden" {...swipeHandlers}>
      {/* Sliding container */}
      <div
        className="flex h-full"
        style={{
          width: '200%',
          transform: `translateX(-${panel * 50}%)`,
          transition: 'transform 0.35s cubic-bezier(0.4, 0, 0.2, 1)',
        }}
      >
        {/* Panel 0: Home (app grid) */}
        <div className="h-full w-1/2 overflow-y-auto">
          <Home />
        </div>

        {/* Panel 1: Dashboard Canvas */}
        <div className="h-full w-1/2 overflow-y-auto">
          <React.Suspense
            fallback={
              <div
                className="flex h-full items-center justify-center"
                style={{ backgroundColor: 'var(--base)' }}
              >
                <div
                  className="h-6 w-6 animate-spin rounded-full border-2 border-t-transparent"
                  style={{
                    borderColor: 'var(--accent)',
                    borderTopColor: 'transparent',
                  }}
                />
              </div>
            }
          >
            <DashboardCanvas />
          </React.Suspense>
        </div>
      </div>

      {/* Bottom dots indicator (mobile) */}
      <div className="absolute bottom-4 left-1/2 -translate-x-1/2 flex gap-2 md:hidden">
        {[0, 1].map((i) => (
          <button
            type="button"
            key={i}
            onClick={() => setPanel(i)}
            className="h-2 w-2 rounded-full transition-all"
            style={{
              backgroundColor:
                panel === i ? 'rgba(255, 255, 255, 0.7)' : 'rgba(255, 255, 255, 0.2)',
              transform: panel === i ? 'scale(1.2)' : 'scale(1)',
            }}
            aria-label={i === 0 ? '應用列表' : 'Dashboard'}
          />
        ))}
      </div>
    </div>
  )
}
