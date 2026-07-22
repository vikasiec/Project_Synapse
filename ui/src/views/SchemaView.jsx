import { useCallback, useEffect, useMemo, useState } from 'react'
import ReactFlow, { Background, Controls, MarkerType, applyNodeChanges } from 'reactflow'
import 'reactflow/dist/style.css'
import { api } from '../api'
import {
  CARD_W,
  COLUMNS,
  CONFIRMED_COLOR,
  CORRECTED_COLOR,
  relationshipKey,
  estimateCardHeight,
  masonryPosition,
  sourceNodeId,
} from '../schemaShared'
import ExplanationDrawer from './ExplanationDrawer'
import SourcePropertiesPanel from './SourcePropertiesPanel'
import SourceGroupNode from './SourceGroupNode'
import './ExploreView.css'

const NODE_TYPES = { sourceGroup: SourceGroupNode }

function fieldFromHandle(nodeId, handleId, prefix) {
  const sourceSystem = nodeId.startsWith('src:') ? nodeId.slice(4) : nodeId
  const fieldName = handleId && handleId.startsWith(prefix) ? handleId.slice(prefix.length) : handleId
  return { source_system: sourceSystem, field_name: fieldName }
}

// The Schema tab: every landed source rendered at once (not one-at-a-time
// like Explore), every already-confirmed relationship drawn simultaneously
// as a real ERD, canvas position saved server-side per drag so a
// deliberately-arranged diagram looks the same on the next visit, and a
// hand-drawn field-to-field connection routes through the exact same
// ACCEPT/REJECT/RELABEL drawer Explore uses -- no second curation path.
export default function SchemaView() {
  const [sources, setSources] = useState([])
  const [profilesBySource, setProfilesBySource] = useState({})
  const [relationships, setRelationships] = useState([])
  const [layout, setLayout] = useState({}) // source_system -> {x, y}
  const [nodes, setNodes] = useState([])
  const [selected, setSelected] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [propertiesSource, setPropertiesSource] = useState(null)

  const loadAll = useCallback(async () => {
    try {
      const [exploreData, ontologyData, layoutData] = await Promise.all([
        api.explore(),
        api.ontology(),
        api.getLayout(),
      ])
      const list = exploreData.sources || []
      setSources(list)
      setRelationships(ontologyData.relationships || [])
      const layoutMap = {}
      for (const p of layoutData.positions || []) {
        layoutMap[p.source_system] = { x: p.x, y: p.y }
      }
      setLayout(layoutMap)

      const entries = await Promise.all(
        list.map(async (s) => {
          try {
            const p = await api.profile(s.source_system)
            return [s.source_system, p.fields || []]
          } catch {
            return [s.source_system, []]
          }
        }),
      )
      setProfilesBySource(Object.fromEntries(entries))
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => {
    loadAll()
  }, [loadAll])

  const onOpenProperties = useCallback((sourceSystem) => setPropertiesSource(sourceSystem), [])

  // Recompute base layout when sources/profiles change, preserving any
  // position the user already dragged (and hasn't been overwritten by a
  // fresh loadAll() yet) -- same merge pattern ExploreView uses so drag
  // state survives incidental re-renders.
  useEffect(() => {
    setNodes((prev) => {
      const prevById = new Map(prev.map((n) => [n.id, n]))
      const heights = sources.map((s) => estimateCardHeight((profilesBySource[s.source_system] || []).length))
      const colHeights = new Array(COLUMNS).fill(0)
      return sources.map((s, i) => {
        const id = sourceNodeId(s.source_system)
        const existing = prevById.get(id)
        const saved = layout[s.source_system]
        const fallback = masonryPosition(i, heights, colHeights)
        const position = existing ? existing.position : saved || fallback
        return {
          id,
          type: 'sourceGroup',
          position,
          draggable: true,
          data: {
            sourceSystem: s.source_system,
            fields: profilesBySource[s.source_system] || null,
            active: false,
            fieldHandles: true,
            onActivate: () => {},
            onOpenProperties: () => onOpenProperties(s.source_system),
          },
          style: { width: CARD_W, ...(existing ? existing.style : {}) },
        }
      })
    })
  }, [sources, profilesBySource, layout, onOpenProperties])

  const onNodesChange = useCallback((changes) => {
    setNodes((nds) => applyNodeChanges(changes, nds))
  }, [])

  const onNodeDragStop = useCallback(async (_evt, node) => {
    try {
      await api.saveLayoutPosition(node.data.sourceSystem, node.position.x, node.position.y)
    } catch (e) {
      setError(e.message)
    }
  }, [])

  const edges = useMemo(() => {
    return relationships.map((r) => {
      const isCorrected = r.predicate !== 'SAME_ENTITY_AS'
      const stroke = isCorrected ? CORRECTED_COLOR : CONFIRMED_COLOR
      return {
        id: `rel:${r.relationship_id}`,
        source: sourceNodeId(r.source_a.source_system),
        sourceHandle: `out-${r.source_a.field_name}`,
        target: sourceNodeId(r.source_b.source_system),
        targetHandle: `in-${r.source_b.field_name}`,
        label: `${r.source_a.field_name} ↔ ${r.source_b.field_name}${isCorrected ? ` (${r.predicate})` : ''}`,
        style: { stroke, strokeWidth: 3 },
        markerEnd: { type: MarkerType.ArrowClosed, color: stroke },
        labelStyle: { fill: '#e6e8ee', fontSize: 10 },
        labelBgStyle: { fill: '#12151c' },
      }
    })
  }, [relationships])

  const onConnect = useCallback(
    async (params) => {
      const a = fieldFromHandle(params.source, params.sourceHandle, 'out-')
      const b = fieldFromHandle(params.target, params.targetHandle, 'in-')
      if (!a.field_name || !b.field_name) return
      setBusy(true)
      setError(null)
      try {
        const result = await api.analyzePair(a.source_system, a.field_name, b.source_system, b.field_name)
        const candidate = (result.candidates || [])[0]
        if (candidate) setSelected(candidate)
      } catch (e) {
        setError(e.message)
      } finally {
        setBusy(false)
      }
    },
    [],
  )

  const confirmedForSelected = useMemo(() => {
    if (!selected) return null
    const match = relationships.find(
      (r) => relationshipKey(r.source_a, r.source_b) === relationshipKey(selected.source_a, selected.source_b),
    )
    return match ? { relationship_id: match.relationship_id, predicate: match.predicate } : null
  }, [selected, relationships])

  const handleDecide = useCallback(
    async (action, extra) => {
      if (!selected) return
      setBusy(true)
      setError(null)
      try {
        const payload = confirmedForSelected
          ? { ...extra, relationship_id: confirmedForSelected.relationship_id }
          : extra
        await api.decide(action, selected.candidate_id, payload)
        if (action === 'ACCEPT' || action === 'RELABEL') {
          await loadAll()
        }
        setSelected(null)
      } catch (e) {
        setError(e.message)
      } finally {
        setBusy(false)
      }
    },
    [selected, confirmedForSelected, loadAll],
  )

  return (
    <div className="explore-shell">
      <div className="explore-upload">
        {sources.length > 0 && (
          <span className="explore-hint">
            {sources.length} source{sources.length === 1 ? '' : 's'}, {relationships.length} confirmed relationship
            {relationships.length === 1 ? '' : 's'} — drag a source to arrange it (saved automatically), or drag
            from one field's edge to another to define a new relationship.
          </span>
        )}
        {busy && <span className="explore-hint busy">Working…</span>}
        {error && <div className="explore-error">{error}</div>}
      </div>

      <div className="explore-canvas">
        {sources.length === 0 ? (
          <div className="canvas-empty">
            No sources loaded yet — go to Explore to bring in data first, then come back here to see it
            all connected.
          </div>
        ) : (
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={NODE_TYPES}
            onNodesChange={onNodesChange}
            onNodeDragStop={onNodeDragStop}
            onConnect={onConnect}
            fitView
            proOptions={{ hideAttribution: true }}
          >
            <Background color="#1c2130" gap={24} />
            <Controls />
          </ReactFlow>
        )}
      </div>

      {propertiesSource && (
        <SourcePropertiesPanel
          sourceSystem={propertiesSource}
          fields={profilesBySource[propertiesSource] || []}
          onClose={() => setPropertiesSource(null)}
        />
      )}

      {selected && (
        <ExplanationDrawer
          candidate={selected}
          alternates={[]}
          confirmed={confirmedForSelected}
          samples={null}
          samplesLoading={false}
          busy={busy}
          onClose={() => setSelected(null)}
          onDecide={handleDecide}
        />
      )}
    </div>
  )
}
