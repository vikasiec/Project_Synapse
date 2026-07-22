import { useEffect, useState } from 'react'
import { api } from '../api'
import './ProfilePreview.css'

// Spec journey step 2: "show profiling output as it's computed" -- a
// lightweight preview of what SYNAPSE actually derived for the picked
// source's fields (data_type / entropy / regex matches), before the user
// commits to scoring it against another source.
export default function ProfilePreview({ source }) {
  const [fields, setFields] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!source) {
      setFields(null)
      return
    }
    let cancelled = false
    api
      .profile(source)
      .then((d) => {
        if (!cancelled) setFields(d.fields || [])
      })
      .catch((e) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
  }, [source])

  if (!source) return null
  if (error) return <div className="profile-preview error">Profiling failed: {error}</div>
  if (!fields) return <div className="profile-preview">Profiling {source}…</div>
  if (fields.length === 0) return null

  return (
    <div className="profile-preview">
      <span className="profile-preview-label">{source} fields</span>
      <div className="profile-chips">
        {fields.map((f) => (
          <span key={f.field_name} className="profile-chip" title={`entropy ${f.entropy_score}`}>
            {f.field_name} <em>{f.data_type}</em>
          </span>
        ))}
      </div>
    </div>
  )
}
