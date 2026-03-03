import type React from 'react'

interface PluginSlotProps {
  name: string
  fallback?: React.ReactNode
}

export function PluginSlot({ name, fallback }: PluginSlotProps) {
  // Future: render registered plugin UI for this slot
  return <>{fallback || null}</>
}
