import { useMemo } from 'react'
import type { MemoryBlock } from '@/types'
import type { Cluster, GalaxyLayer, GalaxyLink, GalaxyNode, Triple, WisdomNode } from '../types'

interface UseGalaxyOptions {
  blocks: MemoryBlock[]
  triples: Triple[]
  clusters: Cluster[]
  wisdom: WisdomNode[]
  visibleLayers: Set<GalaxyLayer>
}

export function useGalaxy({ blocks, triples, clusters, wisdom, visibleLayers }: UseGalaxyOptions) {
  const nodes: GalaxyNode[] = useMemo(() => {
    const result: GalaxyNode[] = []

    if (visibleLayers.has('blocks')) {
      for (const b of blocks) {
        result.push({
          id: b.id,
          label: b.content.slice(0, 40),
          type: b.block_type,
          confidence: b.confidence,
          layer: 'blocks',
        })
      }
    }

    if (visibleLayers.has('triples')) {
      // Limit to first 200 for performance
      for (const t of triples.slice(0, 200)) {
        result.push({
          id: t.id,
          label: `${t.subject} → ${t.predicate}`,
          type: 'knowledge',
          confidence: 0.5,
          layer: 'triples',
        })
      }
    }

    if (visibleLayers.has('clusters')) {
      for (const c of clusters) {
        result.push({
          id: c.id,
          label: c.name,
          type: 'knowledge',
          confidence: 0.7,
          layer: 'clusters',
        })
      }
    }

    if (visibleLayers.has('wisdom')) {
      for (const w of wisdom) {
        const conf = w.confidence === 'HIGH' ? 0.9 : w.confidence === 'MEDIUM' ? 0.6 : 0.3
        result.push({
          id: w.id,
          label: w.wisdom.slice(0, 50),
          type: 'knowledge',
          confidence: conf,
          layer: 'wisdom',
        })
      }
    }

    return result
  }, [blocks, triples, clusters, wisdom, visibleLayers])

  const links: GalaxyLink[] = useMemo(() => {
    const result: GalaxyLink[] = []
    const nodeIds = new Set(nodes.map((n) => n.id))

    // Block-to-block links (tag overlap) — only if blocks visible
    if (visibleLayers.has('blocks')) {
      for (let i = 0; i < blocks.length; i++) {
        for (let j = i + 1; j < blocks.length; j++) {
          const shared = blocks[i].tags.filter((t) => blocks[j].tags.includes(t))
          if (shared.length > 0) {
            result.push({
              source: blocks[i].id,
              target: blocks[j].id,
              strength: shared.length / Math.max(blocks[i].tags.length, blocks[j].tags.length, 1),
            })
          }
        }
      }
    }

    // Wisdom → Cluster links
    if (visibleLayers.has('wisdom') && visibleLayers.has('clusters')) {
      for (const w of wisdom) {
        for (const cid of w.cluster_ids) {
          if (nodeIds.has(cid)) {
            result.push({
              source: w.id,
              target: cid,
              strength: 0.8,
            })
          }
        }
      }
    }

    return result
  }, [nodes, blocks, wisdom, visibleLayers])

  return { nodes, links }
}
