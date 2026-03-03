import { Handle, type NodeProps, Position } from '@xyflow/react'
import type { NodeType } from '../types'
import { NODE_TYPE_CONFIG } from '../types'

interface CustomNodeData {
  label: string
  nodeType: NodeType
  config?: Record<string, unknown> | null
  [key: string]: unknown
}

export default function CustomNode({ data }: NodeProps) {
  const nodeData = data as unknown as CustomNodeData
  const cfg = NODE_TYPE_CONFIG[nodeData.nodeType] || { label: '未知', color: 'var(--overlay1)' }
  const isCondition = nodeData.nodeType === 'condition'

  return (
    <div
      className="min-w-[140px] rounded-lg border-2 px-3 py-2 shadow-md"
      style={{
        backgroundColor: 'var(--surface0)',
        borderColor: cfg.color,
      }}
    >
      <Handle
        type="target"
        position={Position.Top}
        style={{ backgroundColor: cfg.color, width: 8, height: 8 }}
      />

      <div className="flex items-center gap-2">
        <div className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: cfg.color }} />
        <span className="text-xs font-medium" style={{ color: 'var(--subtext0)' }}>
          {cfg.label}
        </span>
      </div>
      <div className="mt-1 text-sm font-semibold" style={{ color: 'var(--text)' }}>
        {nodeData.label}
      </div>

      {isCondition ? (
        <>
          <Handle
            type="source"
            position={Position.Bottom}
            id="true"
            style={{
              backgroundColor: 'var(--green)',
              width: 8,
              height: 8,
              left: '30%',
            }}
          />
          <Handle
            type="source"
            position={Position.Bottom}
            id="false"
            style={{
              backgroundColor: 'var(--red)',
              width: 8,
              height: 8,
              left: '70%',
            }}
          />
        </>
      ) : (
        <Handle
          type="source"
          position={Position.Bottom}
          id="output"
          style={{ backgroundColor: cfg.color, width: 8, height: 8 }}
        />
      )}
    </div>
  )
}
