import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import CatalogView from './views/CatalogView'
import ExploreView from './views/ExploreView'
import ResolveView from './views/ResolveView'
import SchemaView from './views/SchemaView'
import SuperSchemaView from './views/SuperSchemaView'
import WarehouseView from './views/WarehouseView'
import './App.css'

const TABS = [
  { id: 'explore', label: 'Explore' },
  { id: 'resolve', label: 'Resolve' },
  { id: 'schema', label: 'Schema' },
  { id: 'catalog', label: 'Catalog' },
  { id: 'super-schema', label: 'Super Schema' },
  { id: 'warehouse', label: 'Warehouse' },
]

const LAST_WORKSPACE_KEY = 'synapse.lastWorkspaceId'

// The actual journey now starts here: create a workspace, import sources
// into it, run the relationship-discovery journey within it -- that
// workspace's confirmed relationships *are* its schema. Every other view
// just receives whichever workspace_id is currently selected; they don't
// know or care how it got picked.
function WorkspaceCreateForm({ onCreated, onCancel, busy, error }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  return (
    <form
      className="workspace-create-form"
      onSubmit={(e) => {
        e.preventDefault()
        if (name.trim()) onCreated(name.trim(), description.trim())
      }}
    >
      <label>
        Workspace name
        <input value={name} onChange={(e) => setName(e.target.value)} autoFocus placeholder="e.g. Lab Ops" />
      </label>
      <label>
        Description (optional)
        <input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="What is this workspace for?" />
      </label>
      {error && <div className="explore-error">{error}</div>}
      <div className="workspace-create-actions">
        <button type="submit" className="file-ingest-btn" disabled={busy || !name.trim()}>
          Create workspace
        </button>
        {onCancel && (
          <button type="button" className="file-ingest-btn secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
        )}
      </div>
    </form>
  )
}

function App() {
  const [tab, setTab] = useState('explore')
  const [catalogVersion, setCatalogVersion] = useState(0)
  const [workspaces, setWorkspaces] = useState(null) // null = still loading
  const [workspaceId, setWorkspaceId] = useState(null)
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [createBusy, setCreateBusy] = useState(false)
  const [createError, setCreateError] = useState(null)

  const loadWorkspaces = useCallback(async () => {
    try {
      const data = await api.listWorkspaces()
      const list = data.workspaces || []
      setWorkspaces(list)
      const remembered = localStorage.getItem(LAST_WORKSPACE_KEY)
      const stillExists = list.find((w) => w.workspace_id === remembered)
      if (stillExists) {
        setWorkspaceId(remembered)
      } else if (list.length > 0) {
        setWorkspaceId(list[0].workspace_id)
      }
    } catch {
      setWorkspaces([])
    }
  }, [])

  useEffect(() => {
    loadWorkspaces()
  }, [loadWorkspaces])

  const selectWorkspace = useCallback((id) => {
    setWorkspaceId(id)
    localStorage.setItem(LAST_WORKSPACE_KEY, id)
    setShowCreateForm(false)
  }, [])

  const handleCreate = useCallback(
    async (name, description) => {
      setCreateBusy(true)
      setCreateError(null)
      try {
        const ws = await api.createWorkspace(name, description)
        await loadWorkspaces()
        selectWorkspace(ws.workspace_id)
      } catch (e) {
        setCreateError(e.message)
      } finally {
        setCreateBusy(false)
      }
    },
    [loadWorkspaces, selectWorkspace],
  )

  if (workspaces === null) {
    return (
      <div className="app-shell">
        <div className="workspace-loading">Loading…</div>
      </div>
    )
  }

  // First-run: no workspace exists yet -- this is the real entry point of
  // the journey (create a workspace before anything else is possible).
  if (workspaces.length === 0) {
    return (
      <div className="app-shell">
        <div className="workspace-first-run">
          <h1>SYNAPSE</h1>
          <p>Create a workspace to start bringing in data and discovering relationships.</p>
          <WorkspaceCreateForm onCreated={handleCreate} busy={createBusy} error={createError} />
        </div>
      </div>
    )
  }

  const current = workspaces.find((w) => w.workspace_id === workspaceId)

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">SYNAPSE</div>
        <nav className="tabs">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={`tab ${tab === t.id ? 'active' : ''}`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <div className="workspace-switcher">
          <select
            value={workspaceId || ''}
            onChange={(e) => selectWorkspace(e.target.value)}
            title={current?.description || ''}
          >
            {workspaces.map((w) => (
              <option key={w.workspace_id} value={w.workspace_id}>
                {w.name} ({w.source_count} sources)
              </option>
            ))}
          </select>
          <button className="file-ingest-btn secondary" onClick={() => setShowCreateForm((v) => !v)}>
            + New workspace
          </button>
        </div>
      </header>

      {showCreateForm && (
        <div className="workspace-create-panel">
          <WorkspaceCreateForm
            onCreated={handleCreate}
            onCancel={() => setShowCreateForm(false)}
            busy={createBusy}
            error={createError}
          />
        </div>
      )}

      <main className="content">
        {tab === 'explore' && (
          <ExploreView workspaceId={workspaceId} onCommitted={() => setCatalogVersion((v) => v + 1)} />
        )}
        {tab === 'resolve' && <ResolveView />}
        {tab === 'schema' && <SchemaView workspaceId={workspaceId} />}
        {tab === 'catalog' && <CatalogView workspaceId={workspaceId} refreshKey={catalogVersion} />}
        {tab === 'super-schema' && <SuperSchemaView />}
        {tab === 'warehouse' && <WarehouseView />}
      </main>
    </div>
  )
}

export default App
