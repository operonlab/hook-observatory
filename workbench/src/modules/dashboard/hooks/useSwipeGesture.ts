import { useCallback, useRef } from 'react'

interface SwipeConfig {
  /** Minimum horizontal distance in px to count as swipe */
  threshold?: number
  /** Minimum velocity in px/ms */
  velocityThreshold?: number
  onSwipeLeft?: () => void
  onSwipeRight?: () => void
}

interface TouchState {
  startX: number
  startY: number
  startTime: number
}

/**
 * Returns touch handlers for swipe detection.
 * Only triggers if horizontal movement > vertical movement.
 */
export function useSwipeGesture(config: SwipeConfig) {
  const { threshold = 50, velocityThreshold = 0.3, onSwipeLeft, onSwipeRight } = config
  const touchRef = useRef<TouchState | null>(null)

  const onTouchStart = useCallback((e: React.TouchEvent) => {
    const touch = e.touches[0]
    touchRef.current = {
      startX: touch.clientX,
      startY: touch.clientY,
      startTime: Date.now(),
    }
  }, [])

  const onTouchEnd = useCallback(
    (e: React.TouchEvent) => {
      if (!touchRef.current) return
      const touch = e.changedTouches[0]
      const dx = touch.clientX - touchRef.current.startX
      const dy = touch.clientY - touchRef.current.startY
      const dt = Date.now() - touchRef.current.startTime
      touchRef.current = null

      // Only horizontal swipes
      if (Math.abs(dx) < Math.abs(dy)) return
      if (Math.abs(dx) < threshold) return

      const velocity = Math.abs(dx) / dt
      if (velocity < velocityThreshold) return

      if (dx < 0) {
        onSwipeLeft?.()
      } else {
        onSwipeRight?.()
      }
    },
    [threshold, velocityThreshold, onSwipeLeft, onSwipeRight],
  )

  return { onTouchStart, onTouchEnd }
}
