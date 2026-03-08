import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'

interface ModulePWA {
  manifest: string
  icon: string
  themeColor: string
}

const MODULE_PWA: Record<string, ModulePWA> = {
  memvault: {
    manifest: '/manifest-memvault.json',
    icon: '/icons/icon-memvault-192.png',
    themeColor: '#bdd4fa',
  },
  intelflow: {
    manifest: '/manifest-intelflow.json',
    icon: '/icons/icon-intelflow-192.png',
    themeColor: '#94e2d5',
  },
  finance: {
    manifest: '/manifest-finance.json',
    icon: '/icons/icon-finance-192.png',
    themeColor: '#a6e3a1',
  },
  taskflow: {
    manifest: '/manifest-taskflow.json',
    icon: '/icons/icon-taskflow-192.png',
    themeColor: '#cba6f7',
  },
  ideagraph: {
    manifest: '/manifest-ideagraph.json',
    icon: '/icons/icon-ideagraph-192.png',
    themeColor: '#f9e2af',
  },
  admin: {
    manifest: '/manifest-admin.json',
    icon: '/icons/icon-admin-192.png',
    themeColor: '#a6adc8',
  },
  nodeflow: {
    manifest: '/manifest-nodeflow.json',
    icon: '/icons/icon-nodeflow-192.png',
    themeColor: '#fab387',
  },
  invest: {
    manifest: '/manifest-invest.json',
    icon: '/icons/icon-invest-192.png',
    themeColor: '#f38ba8',
  },
  notification: {
    manifest: '/manifest-notification.json',
    icon: '/icons/icon-notification-192.png',
    themeColor: '#cba6f7',
  },
  briefing: {
    manifest: '/manifest-briefing.json',
    icon: '/icons/icon-briefing-192.png',
    themeColor: '#c9a962',
  },
}

const DEFAULT_PWA: ModulePWA = {
  manifest: '/manifest.json',
  icon: '/icons/icon-192.png',
  themeColor: '#1e1e2e',
}

function setLinkHref(rel: string, href: string) {
  const link = document.querySelector<HTMLLinkElement>(`link[rel="${rel}"]`)
  if (link) {
    link.href = href
  }
}

/**
 * Dynamically swaps <link rel="manifest">, apple-touch-icon,
 * and theme-color based on current route.
 * Allows each module to be installed as a separate PWA.
 */
export function useManifest() {
  const { pathname } = useLocation()

  useEffect(() => {
    const segment = pathname.split('/')[1] || ''
    const pwa = MODULE_PWA[segment] || DEFAULT_PWA

    setLinkHref('manifest', pwa.manifest)
    setLinkHref('apple-touch-icon', pwa.icon)

    const meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
    if (meta) {
      meta.content = pwa.themeColor
    }
  }, [pathname])
}
