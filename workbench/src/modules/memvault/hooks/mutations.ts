import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { MemoryBlockCreate, MemoryBlockUpdate } from '@/types'
import { kgApi, memvaultApi } from '../api'
import { memvaultKeys } from './queries'

export function useCreateBlock() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: MemoryBlockCreate) => memvaultApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['memvault', 'blocks'] })
    },
  })
}

export function useUpdateBlock() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: MemoryBlockUpdate }) =>
      memvaultApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['memvault', 'blocks'] })
    },
  })
}

export function useDeleteBlock() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => memvaultApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['memvault', 'blocks'] })
    },
  })
}

export function useDeleteTriple() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => kgApi.deleteTriple(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['memvault', 'kg', 'triples'] })
    },
  })
}

export function useDeleteAttitude() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => kgApi.deleteAttitude(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['memvault', 'kg', 'attitudes'] })
      queryClient.invalidateQueries({ queryKey: ['memvault', 'kg', 'attitude-history'] })
    },
  })
}

export function useUpdateAttitude() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: { fact: string; category: string } }) =>
      kgApi.updateAttitude(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['memvault', 'kg', 'attitudes'] })
      queryClient.invalidateQueries({ queryKey: ['memvault', 'kg', 'attitude-history'] })
    },
  })
}

export function useRecalculateProfile() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => memvaultApi.recalculateProfile(),
    onSuccess: (data) => {
      queryClient.setQueryData(memvaultKeys.profile(), data)
    },
  })
}
