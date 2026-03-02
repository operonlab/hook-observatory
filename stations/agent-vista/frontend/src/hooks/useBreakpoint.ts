// Responsive breakpoint hook — zero dependencies, useSyncExternalStore

import { useSyncExternalStore } from 'react';

export type Breakpoint = 'mobile' | 'tablet' | 'desktop';

function getBreakpoint(): Breakpoint {
  const w = window.innerWidth;
  if (w < 640) return 'mobile';
  if (w < 1024) return 'tablet';
  return 'desktop';
}

function subscribe(cb: () => void) {
  window.addEventListener('resize', cb);
  return () => window.removeEventListener('resize', cb);
}

export function useBreakpoint(): Breakpoint {
  return useSyncExternalStore(subscribe, getBreakpoint, () => 'desktop');
}

export function isMobile(bp: Breakpoint) { return bp === 'mobile'; }
export function isTablet(bp: Breakpoint) { return bp === 'tablet'; }
export function isDesktop(bp: Breakpoint) { return bp === 'desktop'; }
