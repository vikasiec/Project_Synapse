import { useCallback, useEffect, useMemo, useState } from 'react'
import { Background, Controls, MarkerType, ReactFlow, applyNodeChanges } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { api } from '../api'
import {
  CARD_W,
  COLUMNS,
  CONFIRMED_COLOR,
  CORRECTED_COLOR,
  STATUS_COLOR,
  estimateCardHeight,
  masonryPosition,
  relationshipKey,
  sourceNodeId,
} from '../schemaShared'
import ExplanationDrawer from './ExplanationDrawer'
import FileIngest from './FileIngest'
import SourcePropertiesPanel from './SourcePropertiesPanel'
import SourceGroupNode from './SourceGroupNode'
import './ExploreView.css'

const NODE_TYPES = { sourceGroup: SourceGroupNode }

// Every landed source gets rendered as its own structural cluster
// (header + field:type rows) the moment it's known -- no dropdown pick
// required to see "what's here." Single-click a header to find its
// relations to everything else; double-click (or the header's own
// dedicated button) opens the full properties panel for that source.
function buildStructureNodes(sources, profilesBySource, activeSource, onActivate, onOpenProperties) {
  const heights = sources.map((s) => estimateCardHeight((profilesBySource[s.source_system] || []).length))
  const colHeights = new Array(COLUMNS).fill(0)
  return sources.map((s, i) => {
    const { x, y } = masonryPosition(i, heights, colHeights)
    return {
      id: sourceNodeId(s.source_system),
      type: 'sourceGroup',
      position: { x, y },
      draggable: true,
      data: {
        sourceSystem: s.source_system,
        fields: profilesBySource[s.source_system] || null,
        active: activeSource === s.source_system,
        onActivate: () => onActivate(s.source_system),
        onOpenProperties: () => onOpenProperties(s.source_system),
      },
      style: { width: CARD_W },
    }
  })
}

const fieldNodeId = sourceNodeId

// Multiple CandidateEdges can exist between the same two sources (one per
// matched field pair). Rendering one ReactFlow edge per candidate made
// them stack exactly on top of each other between two source cards --
// visually indistinguishable and impossible to click individually.
// Bundle them into one edge per source pair, ranked by "most interesting
// first" (confirmed/corrected outrank a still-pending recommendation so
// a settled relationship isn't buried under a fresh unrelated guess).
function buildEdges(candidates, confirmedByKey) {
  const withStatus = candidates.map((c) => {
    const confirmed = confirmedByKey.get(relationshipKey(c.source_a, c.source_b))
    return { ...c, _confirmed: confirmed || null }
  })

  const groups = new Map()
  for (const c of withStatus) {
    const key = [c.source_a.source_system, c.source_b.source_system].sort().join('|')
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(c)
  }

  return [...groups.entries()].map(([key, group]) => {
    group.sort((a, b) => {
      const aDecided = a._confirmed ? 1 : 0
      const bDecided = b._confirmed ? 1 : 0
      if (aDecided !== bDecided) return bDecided - aDecided
      return b.similarity_score - a.similarity_score
    })
    const top = group[0]
    const decidedCount = group.filter((c) => c._confirmed).length

    let stroke = STATUS_COLOR[top.status] || '#5b8cff'
    let dashed = false
    let statusLabel = top.status
    if (top._confirmed) {
      const isCorrected = top._confirmed.predicate !== 'SAME_ENTITY_AS'
      stroke = isCorrected ? CORRECTED_COLOR : CONFIRMED_COLOR
      statusLabel = isCorrected ? `corrected: ${top._confirmed.predicate}` : 'confirmed'
    }
    const style = { stroke, strokeWidth: top._confirmed ? 3 : 2 }
    if (dashed) style.strokeDasharray = '4 2'

    const mark = top._confirmed ? '✓ ' : ''
    const label =
      group.length === 1
        ? `${mark}${top.source_a.field_name} ↔ ${top.source_b.field_name} (${top.similarity_score.toFixed(2)})`
        : `${mark}${group.length} field matches${decidedCount ? `, ${decidedCount} confirmed` : ''} (best ${top.similarity_score.toFixed(2)})`

    return {
      id: `bundle:${key}`,
      source: fieldNodeId(top.source_a.source_system),
      target: fieldNodeId(top.source_b.source_system),
      label,
      animated: !top._confirmed && top.status === 'high_confidence',
      style,
      markerEnd: { type: MarkerType.ArrowClosed, color: stroke },
      labelStyle: { fill: '#e6e8ee', fontSize: 10 },
      labelBgStyle: { fill: '#12151c' },
      data: { candidates: group },
    }
  })
}

export default function ExploreView({ workspaceId, onCommitted }) {
  const [sources, setSources] = useState([])
  const [profilesBySource, setProfilesBySource] = useState({})
  const [activeSource, setActiveSource] = useState(null)
  const [candidates, setCandidates] = useState([])
  const [selected, setSelected] = useState(null)
  const [selectedGroup, setSelectedGroup] = useState([])
  const [samples, setSamples] = useState(null) // { a: [...], b: [...] } | null
  const [samplesLoading, setSamplesLoading] = useState(false)
  const [propertiesSource, setPropertiesSource] = useState(null)
  // Confirmed relationships, keyed by relationshipKey() -> {relationship_id,
  // predicate}. This is the Catalog's own durable state (survives restart,
  // per row 50), not session-local -- it's what actually answers "have I
  // already decided this one," not a Set that resets on every re-analyze.
  const [confirmedByKey, setConfirmedByKey] = useState(new Map())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  // Nodes are real controlled state (not a plain derived value) so that
  // manual drag/resize survives re-renders -- previously `nodes` was
  // recomputed fresh via useMemo on every state change (e.g. clicking a
  // header to activate a source), silently discarding any position/size
  // the user had just set. onNodesChange + applyNodeChanges is the
  // standard ReactFlow pattern for this.
  const [nodes, setNodes] = useState([])

  const loadConfirmed = useCallback(async () => {
    try {
      const d = await api.ontology(workspaceId)
      const map = new Map()
      for (const r of d.relationships || []) {
        map.set(relationshipKey(r.source_a, r.source_b), {
          relationship_id: r.relationship_id,
          predicate: r.predicate,
        })
      }
      setConfirmedByKey(map)
    } catch {
      // Non-fatal -- edges just fall back to unconfirmed styling.
    }
  }, [workspaceId])

  const loadLandscape = useCallback(async () => {
    let list = []
    try {
      const d = await api.explore(workspaceId)
      list = d.sources || []
      setSources(list)
    } catch (e) {
      setError(e.message)
      return
    }
    const entries = await Promise.all(
      list.map(async (s) => {
        try {
          const p = await api.profile(s.source_system, workspaceId)
          return [s.source_system, p.fields || []]
        } catch {
          return [s.source_system, []]
        }
      }),
    )
    setProfilesBySource(Object.fromEntries(entries))
  }, [workspaceId])

  useEffect(() => {
    loadLandscape()
    loadConfirmed()
  }, [loadLandscape, loadConfirmed])

  const handleLanded = useCallback(async () => {
    await loadLandscape()
  }, [loadLandscape])

  const activateSource = useCallback(
    async (sourceSystem) => {
      setActiveSource(sourceSystem)
      setBusy(true)
      setError(null)
      setSelected(null)
      try {
        const others = sources.map((s) => s.source_system).filter((s) => s !== sourceSystem)
        const results = await Promise.all(others.map((other) => api.analyze(sourceSystem, other)))
        const merged = results.flatMap((r) => r.candidates || [])
        merged.sort((a, b) => b.similarity_score - a.similarity_score)
        setCandidates(merged)
      } catch (e) {
        setError(e.message)
      } finally {
        setBusy(false)
      }
    },
    [sources],
  )

  // Recompute the base layout when sources/profiles/active change, but
  // preserve any position/size the user already dragged or resized on an
  // existing node instead of snapping it back to the computed default.
  useEffect(() => {
    setNodes((prev) => {
      const prevById = new Map(prev.map((n) => [n.id, n]))
      const base = buildStructureNodes(sources, profilesBySource, activeSource, activateSource, setPropertiesSource)
      return base.map((n) => {
        const existing = prevById.get(n.id)
        if (!existing) return n
        return {
          ...n,
          position: existing.position,
          style: { ...n.style, ...existing.style },
          width: existing.width ?? n.width,
          height: existing.height ?? n.height,
        }
      })
    })
  }, [sources, profilesBySource, activeSource, activateSource])

  const onNodesChange = useCallback((changes) => {
    setNodes((nds) => applyNodeChanges(changes, nds))
  }, [])

  const edges = useMemo(() => buildEdges(candidates, confirmedByKey), [candidates, confirmedByKey])

  const openMatch = useCallback((edge) => {
    const group = edge.data?.candidates || []
    setSelected(group[0] || null)
    setSelectedGroup(group)
    setSamples(null)
  }, [])

  const onEdgeClick = useCallback((_evt, edge) => openMatch(edge), [openMatch])

  const onEdgeDoubleClick = useCallback(
    async (_evt, edge) => {
      openMatch(edge)
      const group = edge.data?.candidates || []
      const top = group[0]
      if (!top) return
      setSamplesLoading(true)
      try {
        const [a, b] = await Promise.all([
          api.samples(top.source_a.source_system, top.source_a.field_name, 5, workspaceId),
          api.samples(top.source_b.source_system, top.source_b.field_name, 5, workspaceId),
        ])
        setSamples({ a: a.values || [], b: b.values || [] })
      } catch (e) {
        setError(e.message)
      } finally {
        setSamplesLoading(false)
      }
    },
    [openMatch, workspaceId],
  )

  const onSelectAlternate = useCallback((candidate) => {
    setSelected(candidate)
    setSamples(null)
  }, [])

  const handleDecide = useCallback(
    async (action, extra) => {
      if (!selected) return
      setBusy(true)
      setError(null)
      try {
        // If this exact field pair is already in the Catalog (e.g. the
        // user is correcting a previous ACCEPT to a different predicate),
        // pass its real relationship_id so the backend updates that row
        // in place instead of minting a duplicate keyed by today's fresh
        // (and therefore unrecognized) candidate_id.
        const existing = confirmedByKey.get(relationshipKey(selected.source_a, selected.source_b))
        const payload = existing ? { ...extra, relationship_id: existing.relationship_id } : extra
        await api.decide(action, selected.candidate_id, payload)
        if (action === 'ACCEPT' || action === 'RELABEL') {
          await loadConfirmed()
          onCommitted?.()
        }
        setSelected(null)
      } catch (e) {
        setError(e.message)
      } finally {
        setBusy(false)
      }
    },
    [selected, onCommitted, confirmedByKey, loadConfirmed],
  )

  return (
    <div className="explore-shell">
      <div className="explore-upload">
        <FileIngest workspaceId={workspaceId} onLanded={handleLanded} />
        {sources.length > 0 && (
          <span className="explore-hint">
            {sources.length} source{sources.length === 1 ? '' : 's'} loaded — click a source's header to
            find its relations, double-click for full properties. Double-click a relation line for sample
            data + recommendation. <span style={{ color: CONFIRMED_COLOR }}>Green</span> = confirmed,{' '}
            <span style={{ color: CORRECTED_COLOR }}>amber</span> = corrected,{' '}
            <span style={{ color: STATUS_COLOR.candidate }}>blue</span> = still a recommendation.
          </span>
        )}
        {busy && <span className="explore-hint busy">Analyzing…</span>}
        {error && <div className="explore-error">{error}</div>}
      </div>

      <div className="explore-canvas">
        {sources.length === 0 ? (
          <div className="canvas-empty">
            Select files or a folder above — every source you bring in shows up here as its own
            structure. Click one to see how it relates to everything else you've loaded.
          </div>
        ) : (
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={NODE_TYPES}
            onNodesChange={onNodesChange}
            onEdgeClick={onEdgeClick}
            onEdgeDoubleClick={onEdgeDoubleClick}
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
          alternates={selectedGroup}
          onSelectAlternate={onSelectAlternate}
          confirmed={confirmedByKey.get(relationshipKey(selected.source_a, selected.source_b)) || null}
          samples={samples}
          samplesLoading={samplesLoading}
          busy={busy}
          onClose={() => {
            setSelected(null)
            setSelectedGroup([])
            setSamples(null)
          }}
          onDecide={handleDecide}
        />
      )}
    </div>
  )
}
