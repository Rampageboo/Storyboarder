import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Background, Controls, Handle, MarkerType, Position, ReactFlow,
  type Edge, type Node, type NodeChange, type NodeProps, type ReactFlowInstance,
} from '@xyflow/react'
import type { Shot } from '../types'
import type { StoryGraph } from '../types/storyGraph'
import { shotDisplayLabel } from '../utils/shotDisplay'
import { shotDisplayVersion, shotHasBoardBackground, shotHasCodexLayer, shotShouldOverlayPreview } from '../utils/shotPreview'
import { ShotThumb } from './ShotThumb'
import '@xyflow/react/dist/style.css'
import './StoryMap.css'

type StoryShotNode = Node<{
  shot: Shot
  index: number
  visualEpoch: number
  onRoute: boolean
  shared: boolean
}, 'storyShot'>

const StoryNode = memo(function StoryNode({ data, selected }: NodeProps<StoryShotNode>) {
  return (
    <div className={'story-map-node' + (selected ? ' is-selected' : '') + (data.onRoute ? ' is-on-route' : '')}>
      <Handle type="target" position={Position.Top} isConnectable={false} />
      <div className="story-map-node-image">
        <ShotThumb shotId={data.shot.shot_id} version={shotDisplayVersion(data.shot, data.visualEpoch, data.index)}
          hasImage={shotShouldOverlayPreview(data.shot)} hasBg={shotHasBoardBackground(data.shot)}
          hasCodex={shotHasCodexLayer(data.shot)} />
      </div>
      <div className="story-map-node-label">
        <span className="story-map-node-number">{String(data.index + 1).padStart(2, '0')}</span>
        <span title={shotDisplayLabel(data.shot)}>{shotDisplayLabel(data.shot)}</span>
        {data.shared ? <span className="story-map-shared" title="Shared by multiple routes">●</span> : null}
      </div>
      <Handle type="source" position={Position.Bottom} isConnectable={false} />
    </div>
  )
})

const nodeTypes = { storyShot: StoryNode }
const mapAriaLabels = {
  'node.a11yDescription.default': 'Press Enter or Space to select this board. Drag with a pointer to arrange boards. Use Tab to move between boards.',
  'node.a11yDescription.keyboardDisabled': 'Press Enter or Space to select this board. Drag with a pointer to arrange boards. Use Tab to move between boards.',
}

function deriveMap(graph: StoryGraph, shots: Shot[]) {
  const known = new Set(shots.map(shot => shot.shot_id))
  const outgoing = new Map<string, Set<string>>()
  const indegree = new Map<string, number>()
  const rank = new Map<string, number>()
  const lane = new Map<string, number>()
  const useCount = new Map<string, number>()
  const edges = new Map<string, Edge>()
  for (const shot of shots) indegree.set(shot.shot_id, 0)
  graph.routes.forEach((route, routeIndex) => {
    route.shot_ids.forEach((id, index) => {
      if (!known.has(id)) return
      if (!lane.has(id)) lane.set(id, routeIndex)
      useCount.set(id, (useCount.get(id) ?? 0) + 1)
      const next = route.shot_ids[index + 1]
      if (!next || !known.has(next)) return
      const key = JSON.stringify([id, next])
      const onRoute = route.id === graph.active_route_id
      const prior = edges.get(key)
      if (!prior || onRoute) {
        edges.set(key, {
          id: key, source: id, target: next, type: 'smoothstep',
          className: onRoute ? 'story-edge-active' : 'story-edge',
          markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
          style: { strokeWidth: onRoute ? 2.5 : 1.4 },
        })
      }
      const neighbors = outgoing.get(id) ?? new Set<string>()
      if (!neighbors.has(next)) {
        neighbors.add(next)
        outgoing.set(id, neighbors)
        indegree.set(next, (indegree.get(next) ?? 0) + 1)
      }
    })
  })
  const queue = shots.filter(shot => indegree.get(shot.shot_id) === 0).map(shot => shot.shot_id)
  // The server validates a DAG; rank aligns joins below all of their incoming branches.
  for (let cursor = 0; cursor < queue.length; cursor += 1) {
    const id = queue[cursor]
    for (const next of outgoing.get(id) ?? []) {
      rank.set(next, Math.max(rank.get(next) ?? 0, (rank.get(id) ?? 0) + 1))
      indegree.set(next, (indegree.get(next) ?? 1) - 1)
      if (indegree.get(next) === 0) queue.push(next)
    }
  }
  const positions: StoryGraph['positions'] = {}
  const occupied = new Map<string, number>()
  shots.forEach((shot, index) => {
    const row = rank.get(shot.shot_id) ?? index
    const column = lane.get(shot.shot_id) ?? graph.routes.length
    const cell = column + ':' + row
    const offset = occupied.get(cell) ?? 0
    occupied.set(cell, offset + 1)
    positions[shot.shot_id] = { x: column * 210 + offset * 180, y: row * 148 }
  })
  return { positions, edges: [...edges.values()], useCount }
}

export function StoryMap({
  graph, shots, selectedShotId, visualEpoch, disabled, compact = false, onSelect, onOpen,
  onUpdate, onError,
}: {
  graph: StoryGraph
  shots: Shot[]
  selectedShotId: string | null
  visualEpoch: number
  disabled: boolean
  compact?: boolean
  onSelect: (shotId: string) => void
  onOpen?: (shotId: string) => void
  onUpdate: (graph: StoryGraph) => Promise<void>
  onError: (error: unknown) => void
}) {
  const [localPositions, setLocalPositions] = useState<StoryGraph['positions']>({})
  const [saving, setSaving] = useState(false)
  const pendingRef = useRef(false)
  const flowRef = useRef<ReactFlowInstance<StoryShotNode, Edge> | null>(null)
  const [previousGraph, setPreviousGraph] = useState(graph)
  if (previousGraph !== graph) {
    setPreviousGraph(graph)
    setLocalPositions({})
  }
  const layout = useMemo(() => deriveMap(graph, shots), [graph, shots])
  const activeIds = useMemo(() => new Set(graph.routes.find(route => route.id === graph.active_route_id)?.shot_ids ?? []), [graph])
  const nodes = useMemo<StoryShotNode[]>(() => shots.map((shot, index) => ({
    id: shot.shot_id,
    type: 'storyShot',
    ariaLabel: shotDisplayLabel(shot),
    ariaRole: 'button',
    position: localPositions[shot.shot_id] ?? graph.positions[shot.shot_id] ?? layout.positions[shot.shot_id],
    selected: selectedShotId === shot.shot_id,
    data: { shot, index, visualEpoch, onRoute: activeIds.has(shot.shot_id), shared: (layout.useCount.get(shot.shot_id) ?? 0) > 1 },
  })), [shots, graph.positions, layout, selectedShotId, visualEpoch, localPositions, activeIds])

  const onNodesChange = useCallback((changes: NodeChange<StoryShotNode>[]) => {
    const moved = changes.filter(change => change.type === 'position' && change.position)
    if (!moved.length) return
    setLocalPositions(current => {
      const next = { ...current }
      for (const change of moved) if (change.type === 'position' && change.position) next[change.id] = change.position
      return next
    })
  }, [])

  const savePosition = async (node: StoryShotNode) => {
    if (disabled || pendingRef.current) return
    const prior = graph.positions[node.id] ?? layout.positions[node.id]
    if (!prior) { setLocalPositions({}); return }
    if (prior.x === node.position.x && prior.y === node.position.y) return
    pendingRef.current = true
    setSaving(true)
    try {
      await onUpdate({ ...graph, positions: { ...graph.positions, [node.id]: node.position } })
    } catch (error) {
      setLocalPositions({})
      onError(error)
    } finally {
      pendingRef.current = false
      setSaving(false)
    }
  }

  useEffect(() => {
    const frame = requestAnimationFrame(() => { void flowRef.current?.fitView({ padding: 0.2, duration: 180 }) })
    return () => cancelAnimationFrame(frame)
  }, [shots.length, graph.routes.length, compact])

  return (
    <div className={'story-map' + (compact ? ' story-map-compact' : '')} aria-label="Story structure"
      onKeyDownCapture={event => {
        if (!(event.target instanceof HTMLElement)) return
        const node = event.target.closest<HTMLElement>('.react-flow__node[data-id]')
        if (!node || !event.currentTarget.contains(node)) return
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          event.stopPropagation()
          const id = node.dataset.id
          if (id && !disabled && !saving && !event.repeat) onSelect(id)
        } else if (event.key.startsWith('Arrow') || event.key === 'Delete' || event.key === 'Backspace') {
          // React Flow's arrow movement only emits local position changes, not
          // our pointer-up persistence. Do not move nodes or fire board shortcuts.
          event.preventDefault()
          event.stopPropagation()
        }
      }}>
      <ReactFlow<StoryShotNode, Edge> nodes={nodes} edges={layout.edges} nodeTypes={nodeTypes}
        onInit={instance => { flowRef.current = instance }}
        onNodesChange={onNodesChange} onNodeDragStop={(_, node) => { void savePosition(node) }}
        onNodeClick={(_, node) => { if (!disabled && !saving) onSelect(node.id) }}
        onNodeDoubleClick={(_, node) => { if (!disabled && !saving) onOpen?.(node.id) }}
        nodesDraggable={!disabled && !saving} nodesConnectable={false} edgesReconnectable={false}
        nodesFocusable edgesFocusable={false} ariaLabelConfig={mapAriaLabels}
        deleteKeyCode={null} multiSelectionKeyCode={null} selectionKeyCode={null}
        minZoom={0.08} maxZoom={2} fitView fitViewOptions={{ padding: 0.2 }}
        colorMode="dark" aria-label="Story map, drag boards to arrange; use route controls to branch or join">
        <Background gap={24} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
      {saving ? <span className="story-map-saving" role="status">Saving layout…</span> : null}
    </div>
  )
}
