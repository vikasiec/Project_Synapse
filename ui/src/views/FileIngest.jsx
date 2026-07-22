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
  // Folder-picked files carry a relative path in webkitRelativePath
  // (e.g. "MySources/customers.csv") -- use the top-level folder name as
  // the source system when present, so a whole folder drop groups into
  // one logical source instead of one-source-per-file.
  const rel = file.webkitRelativePath
  if (rel && rel.includes('/')) {
    return rel.split('/')[0]
  }
  const base = file.name.replace(/\.[^.]+$/, '')
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
  const fileInputRef = useRef(null)
  const folderInputRef = useRef(null)

  const handleFiles = async (fileList) => {
    const files = Array.from(fileList || [])
    if (files.length === 0) return
    setBusy(true)
    setError(null)
    setLog([])
    let lastSource = null
    try {
      for (const file of files) {
        const content = await readFileText(file)
        const sourceSystem = sourceNameFor(file)
        const result = await api.ingestFile(file.name, content, sourceSystem)
        lastSource = result.source_system
        setLog((prev) => [
          ...prev,
          `${file.name} -> ${result.source_system} (${result.objects_landed} object${result.objects_landed === 1 ? '' : 's'})`,
        ])
      }
      if (lastSource) onLanded?.(lastSource)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
      if (folderInputRef.current) folderInputRef.current.value = ''
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
