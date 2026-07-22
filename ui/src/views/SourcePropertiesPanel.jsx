import './SourcePropertiesPanel.css'

// Full per-field detail for one source, opened on node double-click (or
// its info button). The compact structure card only shows field_name +
// data_type; this shows everything the profiler actually computed
// (entropy_score, regex_pattern_match breakdown, sample_count) without
// any extra API call -- the full profile objects are already held by
// ExploreView from the initial GET /v1/explore/profile fetch.
export default function SourcePropertiesPanel({ sourceSystem, fields, onClose }) {
  return (
    <div className="props-panel">
      <div className="props-header">
        <span>{sourceSystem}</span>
        <button className="props-close" onClick={onClose}>
          ×
        </button>
      </div>
      <div className="props-body">
        {fields.length === 0 && <div className="props-empty">No fields detected for this source.</div>}
        {fields.map((f) => (
          <div key={f.field_name} className="props-field">
            <div className="props-field-header">
              <span className="props-field-name">{f.field_name}</span>
              <span className="props-field-type">{f.data_type}</span>
            </div>
            <div className="props-field-stats">
              <span>entropy {f.entropy_score.toFixed(2)}</span>
              <span>{f.sample_count} sample{f.sample_count === 1 ? '' : 's'}</span>
            </div>
            {Object.keys(f.regex_pattern_match || {}).length > 0 && (
              <div className="props-field-patterns">
                {Object.entries(f.regex_pattern_match).map(([pattern, pct]) => (
                  <span key={pattern} className="props-pattern-chip">
                    {pattern} {(pct * 100).toFixed(0)}%
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
