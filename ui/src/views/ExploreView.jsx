import { useCallback, useEffect, useMemo, useState } from 'react'
import ReactFlow, { Background, Controls, MarkerType, applyNodeChanges } from 'reactflow'
import 'reactflow/dist/style.css'
import { api } from '../api'
import ExplanationDrawer from './ExplanationDrawer'
import FileIngest from './FileIngest'
import SourcePropertiesPanel from './SourcePropertiesPanel'
import SourceGroupNode from './SourceGroupNode'
import './ExploreView.css'

const STATUS_COLOR = {
  high_confidence: '#34d399',
  candidate: '#5b8cff',
}

const ROW_H = 26
const HEADER_H = 34
const CARD_W = 240
const GAP_X = 60
const GAP_Y = 40
const COLUMNS = 3

const NODE_TYPES = { sourceGroup: SourceGroupNode }

// Every landed source gets rendered as its own structural cluster
// (header + field:type rows) the moment it's known -- no dropdown pick
// required to see "what's here." Single-click a header to find its
// relations to everything else; double-click (or the header's own
// dedicated button) opens the full properties panel for that source.
function buildStructureNodes(sources, profilesBySource, activeSource, onActivate, onOpenProperties) {
  const heights = sources.map((s) => {
    const fields = profilesBySource[s.source_system] || []
    return HEADER_H + Math.max(fields.length, 1) * ROW_H + 16
  })
  const colHeights = new Array(COLUMNS).fill(0)
  return sources.map((s, i) => {
    const col = i % COLUMNS
    // Simple masonry: put each card under whichever column is currently shortest.
    let target = 0
    for (let c = 1; c < COLUMNS; c++) {
      if (colHeights[c] < colHeights[target]) target = c
    }
    const x = target * (CARD_W + GAP_X) + 20
    const y = colHeights[target] + 20
    colHeights[target] += heights[i] + GAP_Y
    return {
      id: `src:${s.source_system}`,
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

function fieldNodeId(sourceSystem) {
  return `src:${sourceSystem}`
}

// Multiple CandidateEdges can exist between the same two sources (one per
// matched field pair). Rendering one ReactFlow edge per candidate made
// them stack exactly on top of each other between two source cards --
// visually indistinguishable and impossible to click individually.
// Bundle them into one edge per source pair, ranked by score, and pick
// the best from the group when the bundle is clicked; the label states
// how many matches the bundle represents so nothing is hidden.
function buildEdges(candidates, committed) {
  const groups = new Map()
  for (const c of candidates) {
    const key = [c.source_a.source_system, c.source_b.source_system].sort().join('|')
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(c)
  }

  return [...groups.entries()].map(([key, group]) => {
    group.sort((a, b) => b.similarity_score - a.similarity_score)
    const top = group[0]
    const anyCommitted = group.some((c) => committed.has(c.candidate_id))
    const style = { stroke: STATUS_COLOR[top.status] || '#5b8cff', strokeWidth: 2 }
    if (anyCommitted) {
      style.stroke = '#34d399'
      style.strokeDasharray = '4 2'
    }
    const label =
      group.length === 1
        ? `${top.source_a.field_name} ↔ ${top.source_b.field_name} (${top.similarity_score.toFixed(2)})`
        : `${group.length} field matches (best ${top.similarity_score.toFixed(2)})`
    return {
      id: `bundle:${key}`,
      source: fieldNodeId(top.source_a.source_system),
      target: fieldNodeId(top.source_b.source_system),
      label,
      animated: top.status === 'high_confidence',
      style,
      markerEnd: { type: MarkerType.ArrowClosed, color: style.stroke },
      labelStyle: { fill: '#e6e8ee', fontSize: 10 },
      labelBgStyle: { fill: '#12151c' },
      data: { candidates: group },
    }
  })
}

export default function ExploreView({ onCommitted }) {
  const [sources, setSources] = useState([])
  const [profilesBySource, setProfilesBySource] = useState({})
  const [activeSource, setActiveSource] = useState(null)
  const [candidates, setCandidates] = useState([])
  const [selected, setSelected] = useState(null)
  const [selectedGroup, setSelectedGroup] = useState([])
  const [samples, setSamples] = useState(null) // { a: [...], b: [...] } | null
  const [samplesLoading, setSamplesLoading] = useState(false)
  const [propertiesSource, setPropertiesSource] = useState(null)
  const [committed, setCommitted] = useState(new Set())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  // Nodes are real controlled state (not a plain derived value) so that
  // manual drag/resize survives re-renders -- previously `nodes` was
  // recomputed fresh via useMemo on every state change (e.g. clicking a
  // header to activate a source), silently discarding any position/size
  // the user had just set. onNodesChange + applyNodeChanges is the
  // standard ReactFlow pattern for this.
  const [nodes, setNodes] = useState([])

  const loadLandscape = useCallback(async () => {
    let list = []
    try {
      const d = await api.explore()
      list = d.sources || []
      setSources(list)
    } catch (e) {
      setError(e.message)
      return
    }
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
  }, [])

  useEffect(() => {
    loadLandscape()
  }, [loadLandscape])

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
        setCommitted(new Set())
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

  const edges = useMemo(() => buildEdges(candidates, committed), [candidates, committed])

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
          api.samples(top.source_a.source_system, top.source_a.field_name),
          api.samples(top.source_b.source_system, top.source_b.field_name),
        ])
        setSamples({ a: a.values || [], b: b.values || [] })
      } catch (e) {
        setError(e.message)
      } finally {
        setSamplesLoading(false)
      }
    },
    [openMatch],
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
        await api.decide(action, selected.candidate_id, extra)
        if (action === 'ACCEPT' || action === 'RELABEL') {
          setCommitted((prev) => new Set(prev).add(selected.candidate_id))
          onCommitted?.()
        }
        setSelected(null)
      } catch (e) {
        setError(e.message)
      } finally {
        setBusy(false)
      }
    },
    [selected, onCommitted],
  )

  return (
    <div className="explore-shell">
      <div className="explore-upload">
        <FileIngest onLanded={handleLanded} />
        {sources.length > 0 && (
          <span className="explore-hint">
            {sources.length} source{sources.length === 1 ? '' : 's'} loaded — click a source's header to
            find its relations, double-click for full properties. Double-click a relation line for sample
            data + recommendation.
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
