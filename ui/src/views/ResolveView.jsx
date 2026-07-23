import { useEffect, useState } from 'react'
import { api } from '../api'
import './ResolveView.css'

// Graph-First Discovery & Entity Resolution (docs/Graph-First Discovery &
// Entity Resolution.pdf), Step 4: the Curation Canvas for entity merge
// candidates -- "We found 'Justin Mason' in the CRM and 'J. Mason' in the
// Billing logs. Do you want to merge these entities?" -- distinct from
// Explore's field-level candidates (this is entity-level, cross-system).
export default function ResolveView({ workspaceId }) {
  const [candidates, setCandidates] = useState(null)
  const [error, setError] = useState(null)
  const [busyId, setBusyId] = useState(null)
  const [decided, setDecided] = useState({})

  const load = () => {
    setCandidates(null)
    api
      .mergeCandidates(workspaceId)
      .then((d) => setCandidates(d.candidates || []))
      .catch((e) => setError(e.message))
  }

  useEffect(load, [workspaceId])

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

  if (error) return <div className="resolve-empty">Failed to load: {error}</div>
  if (candidates === null) return <div className="resolve-empty">Loading…</div>

  const pending = candidates.filter((c) => !decided[c.candidate_id])

  if (pending.length === 0) {
    return (
      <div className="resolve-empty">
        <h2>No entity merge candidates right now</h2>
        <p>
          As data lands across multiple sources, SYNAPSE watches for the same
          real-world entity showing up under different names — those clusters
          will appear here for you to confirm or dismiss.
        </p>
      </div>
    )
  }

  return (
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
  )
}
