import { useCallback, useEffect, useRef } from "react";
import { useMemvaultStore } from "../stores";

export function useMemorySearch(debounceMs = 300) {
  const {
    searchQuery,
    searchResults,
    isSearching,
    setSearchQuery,
    searchSemantic,
    clearSearch,
  } = useMemvaultStore();

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const debouncedSearch = useCallback(() => {
    if (timerRef.current !== null) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      searchSemantic();
    }, debounceMs);
  }, [debounceMs, searchSemantic]);

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) clearTimeout(timerRef.current);
    };
  }, []);

  const handleQueryChange = useCallback(
    (query: string) => {
      setSearchQuery(query);
      if (query.trim()) {
        debouncedSearch();
      } else {
        clearSearch();
      }
    },
    [setSearchQuery, debouncedSearch, clearSearch],
  );

  const handleSearchNow = useCallback(() => {
    if (timerRef.current !== null) clearTimeout(timerRef.current);
    searchSemantic();
  }, [searchSemantic]);

  return {
    query: searchQuery,
    results: searchResults,
    isSearching,
    setQuery: handleQueryChange,
    searchNow: handleSearchNow,
    clear: clearSearch,
  };
}
