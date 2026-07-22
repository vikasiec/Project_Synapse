import { useCallback, useEffect, useMemo, useState } from 'react'
import { Background, Controls, MarkerType, ReactFlow } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { api } from '../api'
import { CARD_W, CONFIRMED_COLOR, CORRECTED_COLOR, STATUS_COLOR, computeAutoLayout, sourceNodeId } from '../schemaShared'
import ExplanationDrawer from './ExplanationDrawer'
import SourceGroupNode from './SourceGroupNode'
import './ExploreView.css'
import './SuperSchemaView.css'

const NODE_TYPES = { sourceGroup: SourceGroupNode }

// Combines 2+ workspaces into one view: unions their sources and already-
// confirmed relationships, and separately surfaces NEW candidate
// relationships the combination reveals between sources that live in
// different workspaces -- the actual value of combining them, not just a
// side-by-side display of what each workspace already found alone. A
// discovered candidate routes through the exact same ExplanationDrawer
// Accept/Reject flow as Explore/Schema View -- no second curation path.
export default function SuperSchemaView() {
  const [workspaces, setWorkspaces] = useState([])
  const [selectedIds, setSelectedIds] = useState([])
  const [result, setResult] = useState(null)
  const [profilesBySource, setProfilesBySource] = useState({})
  const [selected, setSelected] = useState(null)
  const [samples, setSamples] = useState(null)
  const [samplesLoading, setSamplesLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    api
      .listWorkspaces()
      .then((d) => setWorkspaces(d.workspaces || []))
      .catch((e) => setError(e.message))
  }, [])

  const toggleWorkspace = useCallback((id) => {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }, [])

  const combine = useCallback(async () => {
    if (selectedIds.length < 2) return
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const data = await api.computeSuperSchema(selectedIds)
      setResult(data)
      const entries = await Promise.all(
        data.sources.map(async (s) => {
          try {
            const p = await api.profile(s.source_system, s.workspace_id)
            return [s.source_system, p.fields || []]
          } catch {
            return [s.source_system, []]
          }
        }),
      )
      setProfilesBySource(Object.fromEntries(entries))
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }, [selectedIds])

  const nodes = useMemo(() => {
    if (!result) return []
    const layout = computeAutoLayout(
      result.sources.map((s) => ({ source_system: s.source_system })),
      profilesBySource,
      result.relationships,
    )
    return result.sources.map((s) => ({
      id: sourceNodeId(s.source_system),
      type: 'sourceGroup',
      position: layout[s.source_system] || { x: 0, y: 0 },
      draggable: true,
      data: {
        sourceSystem: s.source_system,
        fields: profilesBySource[s.source_system] || null,
        active: false,
        fieldHandles: false,
        onActivate: () => {},
        onOpenProperties: () => {},
      },
      style: { width: CARD_W },
    }))
  }, [result, profilesBySource])

  const edges = useMemo(() => {
    if (!result) return []
    const confirmed = result.relationships.map((r) => {
      const isCorrected = r.predicate !== 'SAME_ENTITY_AS'
      const stroke = isCorrected ? CORRECTED_COLOR : CONFIRMED_COLOR
      return {
        id: `rel:${r.relationship_id}`,
        source: sourceNodeId(r.source_a.source_system),
        target: sourceNodeId(r.source_b.source_system),
        label: `${r.source_a.field_name} ↔ ${r.source_b.field_name}`,
        style: { stroke, strokeWidth: 3 },
        markerEnd: { type: MarkerType.ArrowClosed, color: stroke },
        labelStyle: { fill: '#e6e8ee', fontSize: 10 },
        labelBgStyle: { fill: '#12151c' },
      }
    })
    const candidates = result.cross_workspace_candidates.map((c) => {
      const stroke = STATUS_COLOR[c.status] || '#5b8cff'
      return {
        id: `cand:${c.candidate_id}`,
        source: sourceNodeId(c.source_a.source_system),
        target: sourceNodeId(c.source_b.source_system),
        label: `${c.source_a.field_name} ↔ ${c.source_b.field_name} (${c.similarity_score.toFixed(2)})`,
        animated: c.status === 'high_confidence',
        style: { stroke, strokeWidth: 2, strokeDasharray: '4 2' },
        markerEnd: { type: MarkerType.ArrowClosed, color: stroke },
        labelStyle: { fill: '#e6e8ee', fontSize: 10 },
        labelBgStyle: { fill: '#12151c' },
        data: { candidate: c },
      }
    })
    return [...confirmed, ...candidates]
  }, [result])

  const onEdgeClick = useCallback(async (_evt, edge) => {
    const candidate = edge.data?.candidate
    if (!candidate) return // already-confirmed edges aren't reopenable here
    setSelected(candidate)
    setSamples(null)
    setSamplesLoading(true)
    try {
      const [a, b] = await Promise.all([
        api.samples(candidate.source_a.source_system, candidate.source_a.field_name),
        api.samples(candidate.source_b.source_system, candidate.source_b.field_name),
      ])
      setSamples({ a: a.values || [], b: b.values || [] })
    } catch (e) {
      setError(e.message)
    } finally {
      setSamplesLoading(false)
    }
  }, [])

  const handleDecide = useCallback(
    async (action, extra) => {
      if (!selected) return
      setBusy(true)
      setError(null)
      try {
        await api.decide(action, selected.candidate_id, extra)
        if (action === 'ACCEPT' || action === 'RELABEL') {
          await combine()
        }
        setSelected(null)
      } catch (e) {
        setError(e.message)
      } finally {
        setBusy(false)
      }
    },
    [selected, combine],
  )

  return (
    <div className="explore-shell">
      <div className="super-schema-picker">
        <span className="explore-hint">Combine 2+ workspaces to discover relationships between them:</span>
        <div className="super-schema-checklist">
          {workspaces.map((w) => (
            <label key={w.workspace_id} className="super-schema-checkbox">
              <input
                type="checkbox"
                checked={selectedIds.includes(w.workspace_id)}
                onChange={() => toggleWorkspace(w.workspace_id)}
              />
              {w.name} ({w.source_count})
            </label>
          ))}
        </div>
        <button className="file-ingest-btn" disabled={selectedIds.length < 2 || busy} onClick={combine}>
          {busy ? 'Combining…' : 'Combine'}
        </button>
        {error && <div className="explore-error">{error}</div>}
      </div>

      {result && result.conflicts.length > 0 && (
        <div className="super-schema-conflicts">
          <div className="super-schema-conflicts-title">
            {result.conflicts.length} conflict{result.conflicts.length === 1 ? '' : 's'}: same field, different definitions across workspaces
          </div>
          {result.conflicts.map((c) => (
            <div key={c.canonical_field} className="super-schema-conflict-row">
              <strong>{c.canonical_field}</strong>
              {Object.entries(c.workspaces).map(([wsId, types]) => {
                const ws = workspaces.find((w) => w.workspace_id === wsId)
                return (
                  <span key={wsId} className="super-schema-conflict-chip">
                    {ws?.name || wsId}: {types.join(', ')}
                  </span>
                )
              })}
            </div>
          ))}
        </div>
      )}

      <div className="explore-canvas">
        {!result ? (
          <div className="canvas-empty">Pick 2 or more workspaces above and click Combine.</div>
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
          alternates={[]}
          confirmed={null}
          samples={samples}
          samplesLoading={samplesLoading}
          busy={busy}
          onClose={() => {
            setSelected(null)
            setSamples(null)
          }}
          onDecide={handleDecide}
        />
      )}
    </div>
  )
}
