import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import './CatalogView.css'

// The "already explored" showcase: everything already confirmed via the
// Explore journey's ACCEPT action, browsable as a growing library rather
// than a settings page.
export default function CatalogView({ workspaceId, refreshKey }) {
  const [ontology, setOntology] = useState(null)
  const [error, setError] = useState(null)
  const [dedupeStatus, setDedupeStatus] = useState(null)
  const [dedupeBusy, setDedupeBusy] = useState(false)

  const load = useCallback(() => {
    api
      .ontology(workspaceId)
      .then(setOntology)
      .catch((e) => setError(e.message))
  }, [workspaceId])

  useEffect(load, [load, refreshKey])

  const handleDedupe = async () => {
    setDedupeBusy(true)
    setDedupeStatus(null)
    try {
      const result = await api.dedupeRelationships()
      setDedupeStatus(
        result.edges_removed > 0
          ? `Removed ${result.edges_removed} duplicate${result.edges_removed === 1 ? '' : 's'} across ${result.groups_deduped} relationship${result.groups_deduped === 1 ? '' : 's'}.`
          : 'No duplicates found.',
      )
      load()
    } catch (e) {
      setError(e.message)
    } finally {
      setDedupeBusy(false)
    }
  }

  if (error) {
    return <div className="catalog-empty">Failed to load catalog: {error}</div>
  }
  if (!ontology) {
    return <div className="catalog-empty">Loading…</div>
  }

  const relationships = ontology.relationships || []
  if (relationships.length === 0) {
    return (
      <div className="catalog-empty">
        <h2>No confirmed relationships yet</h2>
        <p>
          Accept a candidate in the Explore tab and it will show up here —
          this is where SYNAPSE's confirmed institutional memory lives.
        </p>
      </div>
    )
  }

  const bySourcePair = {}
  for (const r of relationships) {
    const key = `${r.source_a.source_system} ↔ ${r.source_b.source_system}`
    bySourcePair[key] = bySourcePair[key] || []
    bySourcePair[key].push(r)
  }

  return (
    <div className="catalog-scroll">
      <div className="catalog-toolbar">
        <button className="catalog-dedupe-btn" onClick={handleDedupe} disabled={dedupeBusy}>
          {dedupeBusy ? 'Cleaning up…' : 'Clean up duplicates'}
        </button>
        {dedupeStatus && <span className="catalog-dedupe-status">{dedupeStatus}</span>}
      </div>
      <div className="catalog-grid">
        {Object.entries(bySourcePair).map(([pair, edges]) => (
          <div key={pair} className="catalog-card">
            <div className="catalog-card-header">{pair}</div>
            {edges.map((e) => (
              <div key={e.relationship_id} className="catalog-edge">
                <div className="catalog-edge-fields">
                  <span className="field-chip">{e.source_a.field_name}</span>
                  <span className="predicate-chip">{e.predicate}</span>
                  <span className="field-chip">{e.source_b.field_name}</span>
                </div>
                <div className="catalog-edge-meta">
                  {e.similarity_score != null && (
                    <span className="score">score {e.similarity_score.toFixed(2)}</span>
                  )}
                  <span className="accepted-at">{e.accepted_at}</span>
                </div>
                {e.match_reasons?.length > 0 && (
                  <details className="catalog-reasons">
                    <summary>Why this was linked</summary>
                    <ul>
                      {e.match_reasons.map((r, i) => (
                        <li key={i}>{r}</li>
                      ))}
                    </ul>
                  </details>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}
