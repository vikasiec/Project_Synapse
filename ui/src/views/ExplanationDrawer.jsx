import { useEffect, useState } from 'react'
import './ExplanationDrawer.css'

const PREDICATES = ['SAME_ENTITY_AS', 'FOREIGN_KEY_TO', 'DERIVED_FROM']

// Shows the full match_reasons array for a candidate edge and dispatches
// the ACCEPT / REJECT / RELABEL curation micro-actions. When multiple
// field pairs matched between the same two sources, `alternates` lets the
// user switch which one they're looking at without closing the drawer.
// `samples` ({a, b} arrays of actual observed values, only fetched on an
// edge double-click, not every single-click) gives the reviewer something
// concrete to eyeball alongside the recommendation. `confirmed` (from the
// durable Catalog, not session state) tells the user -- and this drawer --
// whether they're looking at a fresh recommendation or something already
// decided, so re-opening it doesn't present a settled relationship as if
// it were still pending.
export default function ExplanationDrawer({
  candidate,
  alternates = [],
  onSelectAlternate,
  confirmed,
  samples,
  samplesLoading,
  busy,
  onClose,
  onDecide,
}) {
  const [predicate, setPredicate] = useState(confirmed?.predicate || 'SAME_ENTITY_AS')

  useEffect(() => {
    setPredicate(confirmed?.predicate || 'SAME_ENTITY_AS')
  }, [confirmed, candidate.candidate_id])

  return (
    <div className="drawer">
      <div className="drawer-header">
        <span>{confirmed ? 'Confirmed relationship' : 'Candidate match'}</span>
        <button className="drawer-close" onClick={onClose}>
          ×
        </button>
      </div>

      {confirmed && (
        <div className={`drawer-confirmed-badge ${confirmed.predicate !== 'SAME_ENTITY_AS' ? 'corrected' : ''}`}>
          {confirmed.predicate !== 'SAME_ENTITY_AS'
            ? `✓ Corrected to ${confirmed.predicate}`
            : '✓ Confirmed as SAME_ENTITY_AS'}
          — this is already in the Catalog, not just a suggestion.
        </div>
      )}

      {alternates.length > 1 && (
        <div className="drawer-alternates">
          <div className="drawer-section-title">{alternates.length} field matches between these sources</div>
          {alternates.map((c) => (
            <button
              key={c.candidate_id}
              className={`drawer-alt ${c.candidate_id === candidate.candidate_id ? 'active' : ''} ${c._confirmed ? 'decided' : ''}`}
              onClick={() => onSelectAlternate?.(c)}
            >
              {c._confirmed ? '✓ ' : ''}
              {c.source_a.field_name} ↔ {c.source_b.field_name}
              <span>{c._confirmed ? c._confirmed.predicate : c.similarity_score.toFixed(2)}</span>
            </button>
          ))}
        </div>
      )}

      <div className="drawer-fields">
        <div className="field-block">
          <div className="field-source">{candidate.source_a.source_system}</div>
          <div className="field-name">{candidate.source_a.field_name}</div>
        </div>
        <div className="field-arrow">↔</div>
        <div className="field-block">
          <div className="field-source">{candidate.source_b.source_system}</div>
          <div className="field-name">{candidate.source_b.field_name}</div>
        </div>
      </div>

      <div className="drawer-score">
        score {candidate.similarity_score.toFixed(2)} · {candidate.status}
      </div>

      {(samplesLoading || samples) && (
        <div className="drawer-section">
          <div className="drawer-section-title">Sample data (double-click a match to load)</div>
          {samplesLoading && <div className="drawer-samples-loading">Loading samples…</div>}
          {samples && (
            <div className="drawer-samples">
              <div className="drawer-samples-col">
                {samples.a.length === 0 && <div className="drawer-samples-empty">no samples</div>}
                {samples.a.map((v, i) => (
                  <div key={i} className="drawer-sample-value">
                    {v}
                  </div>
                ))}
              </div>
              <div className="drawer-samples-col">
                {samples.b.length === 0 && <div className="drawer-samples-empty">no samples</div>}
                {samples.b.map((v, i) => (
                  <div key={i} className="drawer-sample-value">
                    {v}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      <div className="drawer-section">
        <div className="drawer-section-title">Why SYNAPSE suggested this</div>
        <ul className="reasons-list">
          {candidate.match_reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      </div>

      <div className="drawer-section">
        <div className="drawer-section-title">Relationship type</div>
        <select value={predicate} onChange={(e) => setPredicate(e.target.value)}>
          {PREDICATES.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </div>

      <div className="drawer-actions">
        {!confirmed && (
          <button className="btn accept" disabled={busy} onClick={() => onDecide('ACCEPT', { predicate })}>
            Accept
          </button>
        )}
        <button className="btn relabel" disabled={busy} onClick={() => onDecide('RELABEL', { predicate })}>
          {confirmed ? 'Change relationship type' : 'Relabel & commit'}
        </button>
        {!confirmed && (
          <button className="btn reject" disabled={busy} onClick={() => onDecide('REJECT', {})}>
            Reject
          </button>
        )}
      </div>
    </div>
  )
}
