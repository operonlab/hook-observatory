import { request } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import type { Flow, FlowDetail, FlowEdge, FlowNode, FlowRun, FlowRunDetail } from '../types'

// ======================== Flows ========================

export const flowApi = {
  list: (page = 1, pageSize = 20) =>
    request<PaginatedResponse<Flow>>(`/nodeflow/flows?page=${page}&page_size=${pageSize}`),

  get: (id: string) => request<FlowDetail>(`/nodeflow/flows/${id}`),

  create: (data: {
    name: string
    description?: string
    trigger_type?: string
    trigger_config?: Record<string, unknown>
  }) => request<Flow>('/nodeflow/flows', { method: 'POST', body: JSON.stringify(data) }),

  update: (
    id: string,
    data: Partial<{
      name: string
      description: string
      trigger_type: string
      trigger_config: Record<string, unknown>
      status: string
    }>,
  ) => request<Flow>(`/nodeflow/flows/${id}`, { method: 'PUT', body: JSON.stringify(data) }),

  activate: (id: string) => request<Flow>(`/nodeflow/flows/${id}/activate`, { method: 'POST' }),

  pause: (id: string) => request<Flow>(`/nodeflow/flows/${id}/pause`, { method: 'POST' }),

  trigger: (id: string, inputData?: Record<string, unknown>) =>
    request<FlowRun>(`/nodeflow/flows/${id}/trigger`, {
      method: 'POST',
      body: JSON.stringify({ input_data: inputData }),
    }),
}

// ======================== Nodes ========================

export const nodeApi = {
  listByFlow: (flowId: string) => request<FlowNode[]>(`/nodeflow/flows/${flowId}/nodes`),

  create: (data: {
    flow_id: string
    node_type: string
    label: string
    config?: Record<string, unknown>
    position_x?: number
    position_y?: number
  }) => request<FlowNode>('/nodeflow/nodes', { method: 'POST', body: JSON.stringify(data) }),

  update: (
    id: string,
    data: Partial<{
      node_type: string
      label: string
      config: Record<string, unknown>
      position_x: number
      position_y: number
    }>,
  ) => request<FlowNode>(`/nodeflow/nodes/${id}`, { method: 'PUT', body: JSON.stringify(data) }),

  delete: (id: string) => request<void>(`/nodeflow/nodes/${id}`, { method: 'DELETE' }),
}

// ======================== Edges ========================

export const edgeApi = {
  listByFlow: (flowId: string) => request<FlowEdge[]>(`/nodeflow/flows/${flowId}/edges`),

  create: (data: {
    flow_id: string
    source_node_id: string
    target_node_id: string
    source_port?: string
  }) => request<FlowEdge>('/nodeflow/edges', { method: 'POST', body: JSON.stringify(data) }),

  delete: (id: string) => request<void>(`/nodeflow/edges/${id}`, { method: 'DELETE' }),
}

// ======================== Flow Runs ========================

export const flowRunApi = {
  listByFlow: (flowId: string, page = 1, pageSize = 20) =>
    request<PaginatedResponse<FlowRun>>(
      `/nodeflow/flows/${flowId}/runs?page=${page}&page_size=${pageSize}`,
    ),

  get: (id: string) => request<FlowRunDetail>(`/nodeflow/flow-runs/${id}`),
}

// ======================== Actions ========================

export const actionsApi = {
  list: () => request<{ actions: string[] }>('/nodeflow/actions'),
}
