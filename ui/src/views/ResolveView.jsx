import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import './ResolveView.css'
import './SuperSchemaView.css'

// Graph-First Discovery & Entity Resolution (docs/Graph-First Discovery &
// Entity Resolution.pdf), Step 4: the Curation Canvas for entity merge
// candidates -- "We found 'Justin Mason' in the CRM and 'J. Mason' in the
// Billing logs. Do you want to merge these entities?" -- distinct from
// Explore's field-level candidates (this is entity-level, cross-system).
//
// Default scope is the current workspace; the checklist below lets a user
// explicitly include other workspaces too, mirroring Super Schema's
// multi-workspace combine step but for entities -- catches the same
// real-world entity landed under two different workspaces, not just
// within one.
export default function ResolveView({ workspaceId }) {
  const [workspaces, setWorkspaces] = useState([])
  const [selectedIds, setSelectedIds] = useState(workspaceId ? [workspaceId] : [])
  const [candidates, setCandidates] = useState(null)
  const [error, setError] = useState(null)
  const [busyId, setBusyId] = useState(null)
  const [decided, setDecided] = useState({})

  useEffect(() => {
    api
      .listWorkspaces()
      .then((d) => setWorkspaces(d.workspaces || []))
      .catch((e) => setError(e.message))
  }, [])

  // Reset to "current workspace only" whenever the app-level workspace
  // switcher changes -- an explicit re-selection, not silently sticky
  // across an unrelated workspace switch.
  useEffect(() => {
    setSelectedIds(workspaceId ? [workspaceId] : [])
  }, [workspaceId])

  const toggleWorkspace = useCallback((id) => {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }, [])

  const load = () => {
    setCandidates(null)
    setDecided({})
    api
      .mergeCandidates(selectedIds)
      .then((d) => setCandidates(d.candidates || []))
      .catch((e) => setError(e.message))
  }

  useEffect(load, [selectedIds])

  const handleMerge = async (candidate) => {
    setBusyId(candidate.candidate_id)
    setError(null)
    try {
      await api.mergeEntities(candidate.entity_a.entity_id, candidate.entity_b.entity_id, 'Resolve UI merge')
      setDecided((prev) => ({ ...prev, [candidate.candidate_id]: 'merged' }))
    } catch (e) {
      setError(e.message)
    } finally {
      setBusyId(null)
    }
  }

  const handleDismiss = (candidate) => {
    setDecided((prev) => ({ ...prev, [candidate.candidate_id]: 'dismissed' }))
  }

  const picker = (
    <div className="super-schema-picker">
      <span className="explore-hint">Resolving within:</span>
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
    </div>
  )

  if (error) {
    return (
      <div className="resolve-shell">
        {picker}
        <div className="resolve-empty">Failed to load: {error}</div>
      </div>
    )
  }
  if (candidates === null) {
    return (
      <div className="resolve-shell">
        {picker}
        <div className="resolve-empty">Loading…</div>
      </div>
    )
  }

  const pending = candidates.filter((c) => !decided[c.candidate_id])

  if (pending.length === 0) {
    return (
      <div className="resolve-shell">
        {picker}
        <div className="resolve-empty">
          <h2>No entity merge candidates right now</h2>
          <p>
            As data lands across the workspace(s) selected above, SYNAPSE watches
            for the same real-world entity showing up under different names —
            those clusters will appear here for you to confirm or dismiss.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="resolve-shell">
      {picker}
      <div className="resolve-scroll">
        <div className="resolve-list">
          {pending.map((c) => (
          <div key={c.candidate_id} className="resolve-card">
            <div className="resolve-cluster">
              <div className="resolve-entity">
                <div className="resolve-entity-name">{c.entity_a.canonical_name}</div>
                <div className="resolve-entity-meta">
                  {c.entity_a.entity_type} · {c.entity_a.source_systems || 'unknown source'}
                </div>
              </div>
              <div className="resolve-vs">?=</div>
              <div className="resolve-entity">
                <div className="resolve-entity-name">{c.entity_b.canonical_name}</div>
                <div className="resolve-entity-meta">
                  {c.entity_b.entity_type} · {c.entity_b.source_systems || 'unknown source'}
                </div>
              </div>
            </div>
            <div className="resolve-score">
              score {c.similarity_score.toFixed(2)} · {c.status}
            </div>
            <ul className="resolve-reasons">
              {c.match_reasons.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
            <div className="resolve-actions">
              <button
                className="btn accept"
                disabled={busyId === c.candidate_id}
                onClick={() => handleMerge(c)}
              >
                Merge these entities
              </button>
              <button
                className="btn reject"
                disabled={busyId === c.candidate_id}
                onClick={() => handleDismiss(c)}
              >
                Not the same
              </button>
            </div>
          </div>
        ))}
      </div>
      </div>
    </div>
  )
}
