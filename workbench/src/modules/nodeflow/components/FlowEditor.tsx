import {
  addEdge,
  Background,
  BackgroundVariant,
  type Connection,
  Controls,
  MiniMap,
  type NodeTypes,
  ReactFlow,
  type Edge as RFEdge,
  type Node as RFNode,
  useEdgesState,
  useNodesState,
} from '@xyflow/react'
import { useCallback, useMemo } from 'react'
import '@xyflow/react/dist/style.css'

import { edgeApi, nodeApi } from '../api'
import type { FlowDetail, FlowEdge, FlowNode, NodeType } from '../types'
import { NODE_TYPE_CONFIG } from '../types'
import CustomNode from './CustomNode'

interface Props {
  flow: FlowDetail
  onSave?: () => void
}

const nodeTypes: NodeTypes = {
  custom: CustomNode,
}

function toRFNode(n: FlowNode): RFNode {
  return {
    id: n.id,
    type: 'custom',
    position: { x: n.position_x, y: n.position_y },
    data: {
      label: n.label,
      nodeType: n.node_type as NodeType,
      config: n.config,
    },
  }
}

function toRFEdge(e: FlowEdge): RFEdge {
  return {
    id: e.id,
    source: e.source_node_id,
    target: e.target_node_id,
    sourceHandle: e.source_port,
    animated: true,
    style: { stroke: 'var(--overlay1)' },
  }
}

export default function FlowEditor({ flow, onSave }: Props) {
  const initialNodes = useMemo(() => flow.nodes.map(toRFNode), [flow.nodes])
  const initialEdges = useMemo(() => flow.edges.map(toRFEdge), [flow.edges])

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges)

  const onConnect = useCallback(
    async (params: Connection) => {
      if (!params.source || !params.target) return
      setEdges((eds) =>
        addEdge({ ...params, animated: true, style: { stroke: 'var(--overlay1)' } }, eds),
      )

      // Persist to backend
      try {
        await edgeApi.create({
          flow_id: flow.id,
          source_node_id: params.source,
          target_node_id: params.target,
          source_port: params.sourceHandle || 'output',
        })
      } catch {
        // Rollback on error
        setEdges((eds) =>
          eds.filter((e) => !(e.source === params.source && e.target === params.target)),
        )
      }
    },
    [flow.id, setEdges],
  )

  const onNodeDragStop = useCallback(async (_: unknown, node: RFNode) => {
    try {
      await nodeApi.update(node.id, {
        position_x: node.position.x,
        position_y: node.position.y,
      })
    } catch {
      // silent — position is non-critical
    }
  }, [])

  return (
    <div
      className="h-full w-full rounded-xl overflow-hidden"
      style={{ backgroundColor: 'var(--mantle)' }}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeDragStop={onNodeDragStop}
        nodeTypes={nodeTypes}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="var(--surface1)" />
        <Controls
          style={{
            backgroundColor: 'var(--surface0)',
            borderColor: 'var(--surface1)',
            color: 'var(--text)',
          }}
        />
        <MiniMap
          style={{ backgroundColor: 'var(--surface0)' }}
          nodeColor={(node) => {
            const nt = node.data?.nodeType as NodeType | undefined
            return nt ? NODE_TYPE_CONFIG[nt]?.color || 'var(--overlay1)' : 'var(--overlay1)'
          }}
        />
      </ReactFlow>
    </div>
  )
}
