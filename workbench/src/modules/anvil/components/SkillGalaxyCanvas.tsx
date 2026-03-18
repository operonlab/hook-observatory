import ForceGraph3D from '3d-force-graph'
import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { DOMAIN_COLORS, type GraphEdge, type GraphNode } from '../types'

interface SkillGalaxyCanvasProps {
  graphData: { nodes: GraphNode[]; edges: GraphEdge[] }
  activeDomains: Set<string>
  activeEdgeTypes?: Set<string>
  searchQuery?: string
  onNodeClick?: (name: string) => void
  onEmptyClick?: () => void
  selectedSkillName?: string | null
}

const DEFAULT_COLOR = '#5a5e78'

export default function SkillGalaxyCanvas({
  graphData,
  activeDomains,
  activeEdgeTypes,
  searchQuery,
  onNodeClick,
  onEmptyClick,
  selectedSkillName,
}: SkillGalaxyCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const graphRef = useRef<any>(null)
  const selectedIdRef = useRef(selectedSkillName)
  const onNodeClickRef = useRef(onNodeClick)
  const onEmptyClickRef = useRef(onEmptyClick)
  const highlightNodesRef = useRef(new Set<string>())
  const highlightLinksRef = useRef(new Set<any>())
  const nodesRef = useRef(graphData.nodes)
  const edgesRef = useRef(graphData.edges)
  const activeDomainsRef = useRef(activeDomains)
  const activeEdgeTypesRef = useRef(activeEdgeTypes)
  const searchQueryRef = useRef(searchQuery)

  // Keep refs in sync
  useEffect(() => {
    selectedIdRef.current = selectedSkillName
  }, [selectedSkillName])
  useEffect(() => {
    onNodeClickRef.current = onNodeClick
  }, [onNodeClick])
  useEffect(() => {
    onEmptyClickRef.current = onEmptyClick
  }, [onEmptyClick])
  useEffect(() => {
    activeDomainsRef.current = activeDomains
  }, [activeDomains])
  useEffect(() => {
    activeEdgeTypesRef.current = activeEdgeTypes
  }, [activeEdgeTypes])
  useEffect(() => {
    searchQueryRef.current = searchQuery
  }, [searchQuery])

  // Initialize graph (once)
  useEffect(() => {
    if (!containerRef.current) return

    // ── Prepare initial data ──
    const { coloredNodes, linkData, domainGroups } = prepareGraphData(
      graphData.nodes,
      graphData.edges,
      activeDomains,
      searchQuery,
      highlightNodesRef.current,
    )

    const nodeMap: Record<string, any> = {}
    coloredNodes.forEach((n) => {
      nodeMap[n.id] = n
    })

    const graph = ForceGraph3D()(containerRef.current)
      .graphData({ nodes: coloredNodes, links: linkData })
      .backgroundColor('#06060f')
      .showNavInfo(false)

      // ── Node appearance ──
      .nodeVal((n: any) => n.val ?? 4)
      .nodeColor((n: any) => {
        const hl = highlightNodesRef.current
        if (hl.size > 0 && !hl.has(n.id)) return '#1a1a2e'
        const ad = activeDomainsRef.current
        if (ad.size > 0 && !ad.has(n.domain)) return '#1a1a2e'
        const lq = searchQueryRef.current?.toLowerCase() ?? ''
        if (lq && !n.id.toLowerCase().includes(lq)) return '#1a1a2e'
        return DOMAIN_COLORS[n.domain] ?? DEFAULT_COLOR
      })
      .nodeOpacity(0.9)
      .nodeResolution(16)
      .nodeThreeObjectExtend(true)
      .nodeThreeObject((n: any) => {
        if (n.id !== selectedIdRef.current) return undefined as any
        const nVal = n.val ?? 4
        const r = Math.cbrt(nVal) * graph.nodeRelSize()
        const color = DOMAIN_COLORS[n.domain] ?? DEFAULT_COLOR
        const torus = new THREE.Mesh(
          new THREE.TorusGeometry(r * 1.6, r * 0.1, 12, 48),
          new THREE.MeshBasicMaterial({
            color: new THREE.Color(color),
            transparent: true,
            opacity: 0.65,
          }),
        )
        torus.rotation.x = Math.PI * 0.42
        return torus
      })
      .nodeLabel((n: any) => {
        const color = DOMAIN_COLORS[n.domain] ?? DEFAULT_COLOR
        const pin = n.pinned ? ' 📌' : ''
        return `<span style="color:${color};font-family:'SF Mono',monospace;font-size:12px;text-shadow:0 0 4px rgba(0,0,0,0.8)">${n.id}${pin}</span>`
      })

      // ── Link appearance ──
      .linkWidth((l: any) => {
        const et = activeEdgeTypesRef.current
        if (et && !et.has(l.type)) return 0
        const hl = highlightLinksRef.current
        if (hl.size > 0 && !hl.has(l)) return 0.1
        return l.type === 'pipeline' ? 1.2 : l.type === 'enhancement' ? 0.8 : 0.5
      })
      .linkColor((l: any) => {
        const et = activeEdgeTypesRef.current
        if (et && !et.has(l.type)) return 'transparent'
        const hl = highlightLinksRef.current
        if (hl.size > 0 && !hl.has(l)) return 'rgba(60,60,100,0.08)'
        switch (l.type) {
          case 'pipeline':
            return 'rgba(241, 250, 140, 0.35)'
          case 'enhancement':
            return 'rgba(139, 233, 253, 0.3)'
          default:
            return 'rgba(150, 170, 230, 0.25)'
        }
      })
      .linkOpacity(1)
      .linkDirectionalParticles((l: any) => {
        const et = activeEdgeTypesRef.current
        if (et && !et.has(l.type)) return 0
        const hl = highlightLinksRef.current
        return l.type === 'pipeline' && (hl.size === 0 || hl.has(l)) ? 2 : 0
      })
      .linkDirectionalParticleWidth(1)
      .linkDirectionalParticleSpeed(0.005)
      .linkDirectionalParticleColor(() => 'rgba(241, 250, 140, 0.6)')

      // ── Physics ──
      .d3AlphaDecay(0.02)
      .d3VelocityDecay(0.3)

      // ── Interactions ──
      .onNodeClick((node: any) => {
        // Highlight connected nodes + links
        highlightNodesRef.current.clear()
        highlightLinksRef.current.clear()
        highlightNodesRef.current.add(node.id)
        const currentLinks = graph.graphData().links
        currentLinks.forEach((l: any) => {
          const srcId = typeof l.source === 'object' ? l.source.id : l.source
          const tgtId = typeof l.target === 'object' ? l.target.id : l.target
          if (srcId === node.id || tgtId === node.id) {
            highlightNodesRef.current.add(srcId)
            highlightNodesRef.current.add(tgtId)
            highlightLinksRef.current.add(l)
          }
        })
        refreshVisuals(graph)
        onNodeClickRef.current?.(node.id as string)
      })
      .onNodeDragEnd((node: any) => {
        node.fx = node.x
        node.fy = node.y
        node.fz = node.z
        node.pinned = true
      })
      .onBackgroundClick(() => {
        highlightNodesRef.current.clear()
        highlightLinksRef.current.clear()
        refreshVisuals(graph)
        onEmptyClickRef.current?.()
      })
      .warmupTicks(80)
      .cooldownTicks(200)

    graphRef.current = graph

    // ── Apply forces after init (matches original setTimeout 200ms) ──
    setTimeout(() => {
      graph
        .d3Force('link')
        ?.distance((l: any) => {
          if (l.type === 'pipeline') return 40
          if (l.type === 'enhancement') return 50
          return 80 // shares-domain
        })
        .strength((l: any) => {
          // shares-domain: render only, no force pull
          if (l.type === 'shares-domain') return 0
          return 0.2
        })
      graph.d3Force('charge')?.strength(-40).distanceMax(200)
      graph.d3Force('center')?.strength(0.15)

      // Custom clustering force — pull nodes toward domain centroid
      const dg = domainGroups
      graph.d3Force('cluster', (alpha: number) => {
        const strength = 0.3
        for (const group of Object.values(dg)) {
          let cx = 0,
            cy = 0,
            cz = 0
          for (const n of group) {
            cx += n.x || 0
            cy += n.y || 0
            cz += n.z || 0
          }
          const len = group.length
          cx /= len
          cy /= len
          cz /= len
          for (const n of group) {
            if (n.fx != null) continue
            n.vx += (cx - (n.x || 0)) * strength * alpha
            n.vy += (cy - (n.y || 0)) * strength * alpha
            n.vz += (cz - (n.z || 0)) * strength * alpha
          }
        }
      })

      graph.d3ReheatSimulation()
    }, 200)

    // Initial camera — close enough to see ~80% of nodes
    setTimeout(() => {
      graph.cameraPosition({ x: 0, y: 0, z: 550 }, { x: 0, y: 0, z: 0 }, 1000)
    }, 100)

    // Double-click to unpin
    const el = containerRef.current
    const handleDblClick = () => {
      const gd = graph.graphData()
      const sel = selectedIdRef.current
      if (!sel) return
      const node = gd.nodes.find((n: any) => n.id === sel)
      if (node && node.pinned) {
        node.fx = null
        node.fy = null
        node.fz = null
        node.pinned = false
        graph.d3ReheatSimulation()
      }
    }
    el?.addEventListener('dblclick', handleDblClick)

    // Resize observer
    const ro = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect
      if (width > 0 && height > 0) graph.width(width).height(height)
    })
    ro.observe(containerRef.current)

    return () => {
      el?.removeEventListener('dblclick', handleDblClick)
      ro.disconnect()
      if (containerRef.current) containerRef.current.innerHTML = ''
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Reload graph data only when graphData object changes (e.g. after sync)
  useEffect(() => {
    if (!graphRef.current) return
    nodesRef.current = graphData.nodes
    edgesRef.current = graphData.edges

    const { coloredNodes, linkData, domainGroups } = prepareGraphData(
      graphData.nodes,
      graphData.edges,
      activeDomains,
      searchQuery,
      highlightNodesRef.current,
    )

    const graph = graphRef.current
    graph.d3Force('cluster', (alpha: number) => {
      const strength = 0.3
      for (const group of Object.values(domainGroups)) {
        let cx = 0,
          cy = 0,
          cz = 0
        for (const n of group) {
          cx += n.x || 0
          cy += n.y || 0
          cz += n.z || 0
        }
        const len = group.length
        cx /= len
        cy /= len
        cz /= len
        for (const n of group) {
          if (n.fx != null) continue
          n.vx += (cx - (n.x || 0)) * strength * alpha
          n.vy += (cy - (n.y || 0)) * strength * alpha
          n.vz += (cz - (n.z || 0)) * strength * alpha
        }
      }
    })

    graph.graphData({ nodes: coloredNodes, links: linkData })
    refreshVisuals(graph)
  }, [graphData]) // eslint-disable-line react-hooks/exhaustive-deps

  // Domain/edge filter / search — only refresh colors, don't reset positions
  useEffect(() => {
    if (!graphRef.current) return
    refreshVisuals(graphRef.current)
  }, [activeDomains, activeEdgeTypes, searchQuery])

  // Refresh Saturn ring on selection change
  useEffect(() => {
    if (!graphRef.current) return
    graphRef.current.nodeThreeObject(graphRef.current.nodeThreeObject())
  }, [selectedSkillName])

  return <div ref={containerRef} style={{ width: '100%', height: '100%', position: 'relative' }} />
}

// ── Helpers ──

function prepareGraphData(
  nodes: GraphNode[],
  edges: GraphEdge[],
  activeDomains: Set<string>,
  searchQuery: string | undefined,
  highlightNodes: Set<string>,
) {
  const lq = searchQuery?.toLowerCase() ?? ''

  const coloredNodes = nodes.map((n) => {
    const inDomain = activeDomains.size === 0 || activeDomains.has(n.domain)
    const matchesSearch = !lq || n.id.toLowerCase().includes(lq)
    const inHighlight = highlightNodes.size === 0 || highlightNodes.has(n.id)
    const dim = !inDomain || (lq !== '' && !matchesSearch) || !inHighlight
    return {
      ...n,
      color: dim ? '#1a1a2e' : (DOMAIN_COLORS[n.domain] ?? DEFAULT_COLOR),
      pinned: false,
    }
  })

  const nodeSet = new Set(coloredNodes.map((n) => n.id))
  const linkData = edges
    .filter((e) => nodeSet.has(e.source) && nodeSet.has(e.target))
    .map((e) => ({
      source: e.source,
      target: e.target,
      type: e.type,
      strength: e.strength ?? 0.5,
      description: e.description ?? '',
    }))

  const domainGroups: Record<string, any[]> = {}
  coloredNodes.forEach((n) => {
    const d = n.domain || 'general'
    if (!domainGroups[d]) domainGroups[d] = []
    domainGroups[d].push(n)
  })

  return { coloredNodes, linkData, domainGroups }
}

function refreshVisuals(graph: any) {
  graph.nodeColor(graph.nodeColor())
  graph.linkWidth(graph.linkWidth())
  graph.linkColor(graph.linkColor())
  graph.linkDirectionalParticles(graph.linkDirectionalParticles())
}
