import { useCallback, useEffect, useMemo, useState } from 'react'
import ReactFlow, { Background, Controls, MarkerType } from 'reactflow'
import 'reactflow/dist/style.css'
import { api } from '../api'
import ExplanationDrawer from './ExplanationDrawer'
import FileIngest from './FileIngest'
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
// required to see "what's here." Clicking a cluster's header is what
// triggers relation discovery (compares that source's fields against
// every OTHER currently-loaded source), not a prerequisite to seeing
// the data at all.
function buildStructureNodes(sources, profilesBySource, activeSource, onActivate) {
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
  const [committed, setCommitted] = useState(new Set())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

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

  const nodes = useMemo(
    () => buildStructureNodes(sources, profilesBySource, activeSource, activateSource),
    [sources, profilesBySource, activeSource, activateSource],
  )
  const edges = useMemo(() => buildEdges(candidates, committed), [candidates, committed])

  const onEdgeClick = useCallback((_evt, edge) => {
    const group = edge.data?.candidates || []
    setSelected(group[0] || null)
    setSelectedGroup(group)
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
            {sources.length} source{sources.length === 1 ? '' : 's'} loaded — click a source's header below to
            find its relations to everything else.
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
            onEdgeClick={onEdgeClick}
            fitView
            proOptions={{ hideAttribution: true }}
          >
            <Background color="#1c2130" gap={24} />
            <Controls />
          </ReactFlow>
        )}
      </div>

      {selected && (
        <ExplanationDrawer
          candidate={selected}
          alternates={selectedGroup}
          onSelectAlternate={setSelected}
          busy={busy}
          onClose={() => {
            setSelected(null)
            setSelectedGroup([])
          }}
          onDecide={handleDecide}
        />
      )}
    </div>
  )
}
