import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import './FileIngest.css'
import './SuperSchemaView.css'
import './WarehouseView.css'

// Turns a workspace's (or several combined workspaces') confirmed
// relationships into real fact/dimension tables with real data loaded --
// the step after discovery: Explore/Schema View/Super Schema tell you
// what relates to what, this actually builds queryable tables from it.
// Two-step by design (Preview, then Materialize) since fact/dimension
// classification is a judgment call, not a deterministic fact -- same
// review-before-commit shape as everything else in this app.
export default function WarehouseView() {
  const [workspaces, setWorkspaces] = useState([])
  const [selectedIds, setSelectedIds] = useState([])
  const [preview, setPreview] = useState(null)
  const [result, setResult] = useState(null)
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
    setPreview(null)
    setResult(null)
  }, [])

  const runPreview = useCallback(async () => {
    if (selectedIds.length === 0) return
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const data = await api.previewStarSchema(selectedIds)
      setPreview(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }, [selectedIds])

  const runExecute = useCallback(async () => {
    if (selectedIds.length === 0) return
    setBusy(true)
    setError(null)
    try {
      const data = await api.executeStarSchema(selectedIds)
      setResult(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }, [selectedIds])

  return (
    <div className="explore-shell warehouse-shell">
      <div className="super-schema-picker">
        <span className="explore-hint">Build real fact/dimension tables from one or more workspaces:</span>
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
        <button className="file-ingest-btn" disabled={selectedIds.length === 0 || busy} onClick={runPreview}>
          {busy ? 'Working…' : 'Preview'}
        </button>
        {preview && (
          <button className="file-ingest-btn secondary" disabled={busy} onClick={runExecute}>
            Materialize
          </button>
        )}
        {error && <div className="explore-error">{error}</div>}
      </div>

      <div className="warehouse-body">
        {!preview && !result && (
          <div className="canvas-empty">Pick one or more workspaces above and click Preview.</div>
        )}

        {result && (
          <div className="warehouse-result">
            <div className="warehouse-result-title">Materialized to: {result.db_path}</div>
            <table className="warehouse-table">
              <thead>
                <tr>
                  <th>Table</th>
                  <th>Kind</th>
                  <th>Rows</th>
                </tr>
              </thead>
              <tbody>
                {result.tables.map((t) => (
                  <tr key={t.name}>
                    <td>{t.name}</td>
                    <td>{t.kind}</td>
                    <td>{t.row_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {preview && !result && (
          <div className="warehouse-preview">
            <section>
              <h3>Fact tables ({preview.facts.length})</h3>
              {preview.facts.map((f) => (
                <div key={f.table} className="warehouse-plan-card">
                  <div className="warehouse-plan-card-title">
                    {f.table} <span className="warehouse-plan-card-source">from {f.source}</span>
                  </div>
                  <div className="warehouse-plan-row">
                    <strong>Measures:</strong> {f.measures.join(', ') || '(none)'}
                  </div>
                  {f.foreign_keys.map((fk) => (
                    <div key={fk.dimension_table + fk.fact_field} className="warehouse-plan-row">
                      FK <code>{fk.fact_field}</code> → <strong>{fk.dimension_table}</strong> (
                      {fk.dimension_source}.{fk.dimension_key_field})
                    </div>
                  ))}
                </div>
              ))}
            </section>
            <section>
              <h3>Dimension tables ({preview.dimensions.length})</h3>
              {preview.dimensions.map((d) => (
                <div key={d.table} className="warehouse-plan-card">
                  <div className="warehouse-plan-card-title">
                    {d.table} <span className="warehouse-plan-card-source">from {d.sources.join(', ')}</span>
                  </div>
                  <div className="warehouse-plan-row">
                    <strong>Natural key:</strong> {d.natural_key || '(none found)'}
                    {d.natural_key_is_guess && <span className="warehouse-guess-flag"> (best guess, not curated evidence)</span>}
                  </div>
                  <div className="warehouse-plan-row warehouse-plan-columns">{d.columns.join(', ')}</div>
                </div>
              ))}
            </section>
          </div>
        )}
      </div>
    </div>
  )
}
