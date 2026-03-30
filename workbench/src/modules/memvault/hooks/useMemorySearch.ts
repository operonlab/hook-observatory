import { useCallback, useEffect, useRef, useState } from 'react'
import { useMemvaultStore } from '../stores'
import { useSemanticSearch } from './queries'

export function useMemorySearch(debounceMs = 300) {
  const searchQuery = useMemvaultStore((s) => s.searchQuery)
  const setSearchQuery = useMemvaultStore((s) => s.setSearchQuery)
  const clearSearch = useMemvaultStore((s) => s.clearSearch)

  const [debouncedQuery, setDebouncedQuery] = useState('')
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!searchQuery.trim()) {
      setDebouncedQuery('')
      return
    }
    timerRef.current = setTimeout(() => {
      setDebouncedQuery(searchQuery)
    }, debounceMs)
    return () => {
      if (timerRef.current !== null) clearTimeout(timerRef.current)
    }
  }, [searchQuery, debounceMs])

  const { data: results = [], isFetching } = useSemanticSearch(debouncedQuery)

  const handleQueryChange = useCallback(
    (query: string) => {
      setSearchQuery(query)
      if (!query.trim()) {
        clearSearch()
        setDebouncedQuery('')
      }
    },
    [setSearchQuery, clearSearch],
  )

  const handleSearchNow = useCallback(() => {
    if (timerRef.current !== null) clearTimeout(timerRef.current)
    setDebouncedQuery(searchQuery)
  }, [searchQuery])

  const handleClear = useCallback(() => {
    clearSearch()
    setDebouncedQuery('')
  }, [clearSearch])

  return {
    query: searchQuery,
    results,
    isSearching: isFetching,
    setQuery: handleQueryChange,
    searchNow: handleSearchNow,
    clear: handleClear,
  }
}
