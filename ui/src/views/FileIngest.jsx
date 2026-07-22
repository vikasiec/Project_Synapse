import { useRef, useState } from 'react'
import { api } from '../api'
import './FileIngest.css'

function readFileText(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(reader.error)
    reader.readAsText(file)
  })
}

function sourceNameFor(file) {
  // Every file is its own distinct source, whether picked individually or
  // as part of a folder -- a folder full of heterogeneous files (FHIR
  // JSON, CSVs, HL7 messages) must NOT be merged into one blob source
  // (that was a real bug: it mixed unrelated schemas into a single
  // profiled "structure"). webkitRelativePath is only used to keep
  // same-named files from different subfolders distinct.
  const rel = file.webkitRelativePath
  const base = file.name.replace(/\.[^.]+$/, '')
  if (rel && rel.includes('/')) {
    const dir = rel.slice(0, rel.lastIndexOf('/')).split('/').join('_')
    return `${dir}_${base}`
  }
  return base
}

// Explore journey step 1, for real use: let the user pick actual files
// (or a whole folder) from their machine, land them as a new source, then
// hand back the new source_system name so the caller can preselect it in
// the source picker -- closing the "there's no way to bring NEW data in"
// gap the current dropdown-only picker had.
export default function FileIngest({ onLanded }) {
  const [busy, setBusy] = useState(false)
  const [log, setLog] = useState([])
  const [error, setError] = useState(null)
  const [landedAny, setLandedAny] = useState(false)
  const [reprocessing, setReprocessing] = useState(false)
  const [reprocessed, setReprocessed] = useState(false)
  const fileInputRef = useRef(null)
  const folderInputRef = useRef(null)

  const handleFiles = async (fileList) => {
    const files = Array.from(fileList || [])
    if (files.length === 0) return
    setBusy(true)
    setError(null)
    setLog([])
    let lastSource = null
    const failures = []
    // Each file is landed independently -- one slow/failing file (e.g. a
    // huge JSON blob, or a transient network hiccup) must not silently
    // abort every file queued after it. Previously this loop was wrapped
    // in one try/catch around the whole thing, so a single failure meant
    // the rest of an 8-file folder pick never even got attempted.
    for (const file of files) {
      try {
        const content = await readFileText(file)
        const sourceSystem = sourceNameFor(file)
        const result = await api.ingestFile(file.name, content, sourceSystem)
        lastSource = result.source_system
        setLog((prev) => [
          ...prev,
          `${file.name} -> ${result.source_system} (${result.objects_landed} object${result.objects_landed === 1 ? '' : 's'})`,
        ])
      } catch (e) {
        failures.push(`${file.name}: ${e.message}`)
        setLog((prev) => [...prev, `${file.name} -> FAILED (${e.message})`])
      }
    }
    if (failures.length > 0) {
      setError(`${failures.length} of ${files.length} file(s) failed to land: ${failures.join('; ')}`)
    }
    if (lastSource) {
      onLanded?.(lastSource)
      setLandedAny(true)
      setReprocessed(false)
    }
    setBusy(false)
    if (fileInputRef.current) fileInputRef.current.value = ''
    if (folderInputRef.current) folderInputRef.current.value = ''
  }

  const handleReprocess = async () => {
    setReprocessing(true)
    setError(null)
    try {
      await api.reprocess()
      setReprocessed(true)
      onLanded?.(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setReprocessing(false)
    }
  }

  return (
    <div className="file-ingest">
      <span className="file-ingest-label">Bring in data</span>
      <button className="file-ingest-btn" disabled={busy} onClick={() => fileInputRef.current?.click()}>
        Select files…
      </button>
      <button className="file-ingest-btn" disabled={busy} onClick={() => folderInputRef.current?.click()}>
        Select folder…
      </button>
      {landedAny && (
        <button
          className="file-ingest-btn secondary"
          disabled={busy || reprocessing || reprocessed}
          onClick={handleReprocess}
          title="CSV/JSONL uploads land fast without entity extraction (Explore's field matching doesn't need it) -- run this if you also want these sources' records to show up as Resolve-tab merge candidates."
        >
          {reprocessing ? 'Extracting…' : reprocessed ? 'Entities extracted ✓' : 'Extract entities (for Resolve)'}
        </button>
      )}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept=".csv,.json,.jsonl,.txt"
        style={{ display: 'none' }}
        onChange={(e) => handleFiles(e.target.files)}
      />
      <input
        ref={folderInputRef}
        type="file"
        multiple
        webkitdirectory=""
        directory=""
        style={{ display: 'none' }}
        onChange={(e) => handleFiles(e.target.files)}
      />
      {busy && <span className="file-ingest-status">Landing…</span>}
      {error && <span className="file-ingest-error">{error}</span>}
      {log.length > 0 && (
        <div className="file-ingest-log">
          {log.map((line, i) => (
            <div key={i}>{line}</div>
          ))}
        </div>
      )}
    </div>
  )
}
