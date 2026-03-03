import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'

interface ModulePWA {
  manifest: string
  icon: string
  themeColor: string
}

const MODULE_PWA: Record<string, ModulePWA> = {
  memvault: {
    manifest: '/v2/manifest-memvault.json',
    icon: '/v2/icons/icon-memvault-192.png',
    themeColor: '#bdd4fa',
  },
  intelflow: {
    manifest: '/v2/manifest-intelflow.json',
    icon: '/v2/icons/icon-intelflow-192.png',
    themeColor: '#94e2d5',
  },
}

const DEFAULT_PWA: ModulePWA = {
  manifest: '/v2/manifest.json',
  icon: '/v2/icons/icon-192.png',
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
