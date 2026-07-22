import { useState } from 'react'
import './ExplanationDrawer.css'

const PREDICATES = ['SAME_ENTITY_AS', 'FOREIGN_KEY_TO', 'DERIVED_FROM']

// Shows the full match_reasons array for a candidate edge and dispatches
// the ACCEPT / REJECT / RELABEL curation micro-actions. When multiple
// field pairs matched between the same two sources, `alternates` lets the
// user switch which one they're looking at without closing the drawer.
// `samples` ({a, b} arrays of actual observed values, only fetched on an
// edge double-click, not every single-click) gives the reviewer something
// concrete to eyeball alongside the recommendation.
export default function ExplanationDrawer({
  candidate,
  alternates = [],
  onSelectAlternate,
  samples,
  samplesLoading,
  busy,
  onClose,
  onDecide,
}) {
  const [predicate, setPredicate] = useState('SAME_ENTITY_AS')

  return (
    <div className="drawer">
      <div className="drawer-header">
        <span>Candidate match</span>
        <button className="drawer-close" onClick={onClose}>
          ×
        </button>
      </div>

      {alternates.length > 1 && (
        <div className="drawer-alternates">
          <div className="drawer-section-title">{alternates.length} field matches between these sources</div>
          {alternates.map((c) => (
            <button
              key={c.candidate_id}
              className={`drawer-alt ${c.candidate_id === candidate.candidate_id ? 'active' : ''}`}
              onClick={() => {
                setPredicate('SAME_ENTITY_AS')
                onSelectAlternate?.(c)
              }}
            >
              {c.source_a.field_name} ↔ {c.source_b.field_name}
              <span>{c.similarity_score.toFixed(2)}</span>
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
        <button
          className="btn accept"
          disabled={busy}
          onClick={() => onDecide('ACCEPT', { predicate })}
        >
          Accept
        </button>
        <button
          className="btn relabel"
          disabled={busy}
          onClick={() => onDecide('RELABEL', { predicate })}
        >
          Relabel & commit
        </button>
        <button className="btn reject" disabled={busy} onClick={() => onDecide('REJECT', {})}>
          Reject
        </button>
      </div>
    </div>
  )
}
