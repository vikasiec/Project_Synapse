import { useCallback, useEffect, useMemo, useState } from 'react'
import ReactFlow, { Background, Controls, MarkerType } from 'reactflow'
import 'reactflow/dist/style.css'
import { api } from '../api'
import ExplanationDrawer from './ExplanationDrawer'
import FileIngest from './FileIngest'
import ProfilePreview from './ProfilePreview'
import './ExploreView.css'

const STATUS_COLOR = {
  high_confidence: '#34d399',
  candidate: '#5b8cff',
}

function buildGraph(candidates) {
  const nodesById = new Map()
  const addNode = (key, label, col) => {
    if (nodesById.has(key)) return
    nodesById.set(key, { key, label, col })
  }
  candidates.forEach((c) => {
    addNode(`a:${c.source_a.source_system}:${c.source_a.field_name}`, c.source_a.field_name, 0)
    addNode(`b:${c.source_b.source_system}:${c.source_b.field_name}`, c.source_b.field_name, 1)
  })
  const colCounts = [0, 0]
  const nodes = [...nodesById.values()].map((n) => {
    const y = colCounts[n.col] * 90 + 40
    colCounts[n.col] += 1
    return {
      id: n.key,
      position: { x: n.col === 0 ? 60 : 520, y },
      data: { label: n.label },
      style: {
        background: '#181c26',
        color: '#e6e8ee',
        border: '1px solid #262b38',
        borderRadius: 8,
        fontSize: 12,
        padding: 8,
        width: 200,
      },
    }
  })
  const edges = candidates.map((c) => ({
    id: c.candidate_id,
    source: `a:${c.source_a.source_system}:${c.source_a.field_name}`,
    target: `b:${c.source_b.source_system}:${c.source_b.field_name}`,
    label: c.similarity_score.toFixed(2),
    animated: c.status === 'high_confidence',
    style: { stroke: STATUS_COLOR[c.status] || '#5b8cff', strokeWidth: 2 },
    markerEnd: { type: MarkerType.ArrowClosed, color: STATUS_COLOR[c.status] || '#5b8cff' },
    labelStyle: { fill: '#e6e8ee', fontSize: 11 },
    labelBgStyle: { fill: '#12151c' },
  }))
  return { nodes, edges }
}

export default function ExploreView({ onCommitted }) {
  const [sources, setSources] = useState([])
  const [sourceA, setSourceA] = useState('')
  const [sourceB, setSourceB] = useState('')
  const [mode, setMode] = useState('pair') // 'pair' | 'transitive'
  const [candidates, setCandidates] = useState([])
  const [selected, setSelected] = useState(null)
  const [committed, setCommitted] = useState(new Set())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const refreshSources = useCallback(() => {
    return api
      .explore()
      .then((d) => {
        setSources(d.sources || [])
        return d.sources || []
      })
      .catch((e) => {
        setError(e.message)
        return []
      })
  }, [])

  useEffect(() => {
    refreshSources()
  }, [refreshSources])

  const handleLanded = useCallback(
    async (newSourceSystem) => {
      await refreshSources()
      setSourceA(newSourceSystem)
    },
    [refreshSources],
  )

  const runAnalyze = useCallback(async () => {
    if (!sourceA || (mode === 'pair' && !sourceB)) return
    setBusy(true)
    setError(null)
    try {
      const res = await api.analyze(sourceA, mode === 'pair' ? sourceB : undefined)
      setCandidates(res.candidates || [])
      setSelected(null)
      setCommitted(new Set())
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }, [sourceA, sourceB, mode])

  const { nodes, edges } = useMemo(() => buildGraph(candidates), [candidates])

  const onEdgeClick = useCallback(
    (_evt, edge) => {
      const c = candidates.find((cand) => cand.candidate_id === edge.id)
      setSelected(c || null)
    },
    [candidates],
  )

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

  const styledEdges = edges.map((e) =>
    committed.has(e.id)
      ? { ...e, style: { ...e.style, stroke: '#34d399', strokeDasharray: '4 2' } }
      : e,
  )

  return (
    <div className="explore-shell">
      <div className="explore-upload">
        <FileIngest onLanded={handleLanded} />
      </div>
      <div className="explore-steps">
        <div className="step">
          <label>1. Source</label>
          <select value={sourceA} onChange={(e) => setSourceA(e.target.value)}>
            <option value="">Select source…</option>
            {sources.map((s) => (
              <option key={s.source_system} value={s.source_system}>
                {s.source_system}
              </option>
            ))}
          </select>
        </div>
        <div className="step">
          <label>Mode</label>
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="pair">Compare against another source</option>
            <option value="transitive">Discover via known links (transitive)</option>
          </select>
        </div>
        {mode === 'pair' && (
          <div className="step">
            <label>2. Compare with</label>
            <select value={sourceB} onChange={(e) => setSourceB(e.target.value)}>
              <option value="">Select source…</option>
              {sources
                .filter((s) => s.source_system !== sourceA)
                .map((s) => (
                  <option key={s.source_system} value={s.source_system}>
                    {s.source_system}
                  </option>
                ))}
            </select>
          </div>
        )}
        <button className="analyze-btn" disabled={busy} onClick={runAnalyze}>
          {busy ? 'Working…' : 'Analyze'}
        </button>
        {error && <div className="explore-error">{error}</div>}
      </div>

      <ProfilePreview source={sourceA} />
      {mode === 'pair' && <ProfilePreview source={sourceB} />}

      <div className="explore-canvas">
        {candidates.length === 0 ? (
          <div className="canvas-empty">
            Pick a source (and a second one, or transitive mode) and click Analyze
            to see scored field candidates rendered here as a graph.
          </div>
        ) : (
          <ReactFlow
            nodes={nodes}
            edges={styledEdges}
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
          busy={busy}
          onClose={() => setSelected(null)}
          onDecide={handleDecide}
        />
      )}
    </div>
  )
}
