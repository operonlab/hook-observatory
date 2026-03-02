import { useState, useEffect, useRef, useCallback } from "react";

interface UseSWROptions<T> {
  fallback?: T;
  ttl?: number; // ms, default 5 min
  refreshInterval?: number; // ms, 0 = no auto refresh
}

interface CacheEntry<T> {
  data: T;
  ts: number;
}

export function useSWR<T>(
  key: string,
  fetcher: () => Promise<T>,
  options: UseSWROptions<T> = {},
) {
  const { fallback, ttl = 5 * 60 * 1000, refreshInterval = 0 } = options;
  const cacheKey = "ho-cache:" + key;

  // Read cache synchronously on first render
  const cached = useRef<CacheEntry<T> | null>(null);
  if (!cached.current) {
    try {
      const raw = localStorage.getItem(cacheKey);
      if (raw) cached.current = JSON.parse(raw);
    } catch {
      // corrupt cache, ignore
    }
  }

  const [data, setData] = useState<T | null>(
    cached.current?.data ?? fallback ?? null,
  );
  const [loading, setLoading] = useState(!cached.current);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const result = await fetcher();
      setData(result);
      setError(null);
      const entry: CacheEntry<T> = { data: result, ts: Date.now() };
      localStorage.setItem(cacheKey, JSON.stringify(entry));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [cacheKey, fetcher]);

  useEffect(() => {
    const isStale =
      !cached.current || Date.now() - cached.current.ts > ttl;
    if (isStale) refresh();
    else setLoading(false);

    if (refreshInterval > 0) {
      const timer = setInterval(refresh, refreshInterval);
      return () => clearInterval(timer);
    }
  }, [refresh, ttl, refreshInterval]);

  // loading is true only on first load with no cache
  return { data, loading: loading && !data, error, refresh };
}
