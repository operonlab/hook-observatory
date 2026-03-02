// Custom sprite loader — loads user-provided PNG images from /sprites/ endpoint
// Naming convention:
//   ~/.agent-vista/sprites/claude.png   → all Claude agents
//   ~/.agent-vista/sprites/codex.png    → all Codex agents
//   ~/.agent-vista/sprites/gemini.png   → all Gemini agents
//   ~/.agent-vista/sprites/{4char}.png  → specific agent by session ID prefix

const loaded = new Map<string, HTMLImageElement | null>();
const loading = new Set<string>();

/**
 * Get a custom sprite image for the given CLI type and session ID.
 * Returns the image if loaded, null if not available or still loading.
 * Attempts to load on first call (non-blocking).
 */
export function getCustomSprite(cliType: string, sessionId?: string): HTMLImageElement | null {
  // Try agent-specific first (by session ID prefix)
  if (sessionId) {
    const prefix = sessionId.slice(0, 4);
    const agentImg = tryLoad(prefix);
    if (agentImg) return agentImg;
  }

  // Fall back to CLI type
  return tryLoad(cliType);
}

function tryLoad(name: string): HTMLImageElement | null {
  if (loaded.has(name)) return loaded.get(name)!;
  if (loading.has(name)) return null;

  loading.add(name);
  const base = import.meta.env.BASE_URL.replace(/\/$/, '');

  // Use fetch instead of Image.src to avoid browser console 404 errors
  fetch(`${base}/sprites/${name}.png`)
    .then(res => {
      if (!res.ok) throw new Error('not found');
      return res.blob();
    })
    .then(blob => {
      const img = new Image();
      const url = URL.createObjectURL(blob);
      img.onload = () => {
        loaded.set(name, img);
        loading.delete(name);
      };
      img.onerror = () => {
        URL.revokeObjectURL(url);
        loaded.set(name, null);
        loading.delete(name);
      };
      img.src = url;
    })
    .catch(() => {
      loaded.set(name, null); // mark as unavailable
      loading.delete(name);
    });

  return null;
}

/** Check if any custom sprites are available. */
export function hasCustomSprites(): boolean {
  for (const [, img] of loaded) {
    if (img) return true;
  }
  return false;
}
