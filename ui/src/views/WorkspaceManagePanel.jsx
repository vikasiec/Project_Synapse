import { useState } from 'react'
import { api } from '../api'
import './WorkspaceManagePanel.css'

// IDE-style workspace management: one place to see every workspace and act
// on any of them (switch, rename, save-as, delete) instead of only the
// currently-selected one via scattered topbar buttons. Deleting is
// destructive (cascades every source, confirmed relationship, and layout
// entry that belonged to it), so it requires an explicit two-click confirm
// per row rather than a single click.
export default function WorkspaceManagePanel({ workspaces, currentId, onClose, onChanged, onSwitch, onSaveAs }) {
  const [renamingId, setRenamingId] = useState(null)
  const [renameName, setRenameName] = useState('')
  const [renameDesc, setRenameDesc] = useState('')
  const [confirmDeleteId, setConfirmDeleteId] = useState(null)
  const [busyId, setBusyId] = useState(null)
  const [error, setError] = useState(null)

  const startRename = (ws) => {
    setRenamingId(ws.workspace_id)
    setRenameName(ws.name)
    setRenameDesc(ws.description || '')
    setConfirmDeleteId(null)
  }

  const submitRename = async (id) => {
    if (!renameName.trim()) return
    setBusyId(id)
    setError(null)
    try {
      await api.renameWorkspace(id, renameName.trim(), renameDesc.trim())
      setRenamingId(null)
      await onChanged()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusyId(null)
    }
  }

  const submitDelete = async (id) => {
    setBusyId(id)
    setError(null)
    try {
      await api.deleteWorkspace(id)
      setConfirmDeleteId(null)
      await onChanged(id)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="workspace-manage-overlay" onClick={onClose}>
      <div className="workspace-manage-panel" onClick={(e) => e.stopPropagation()}>
        <div className="workspace-manage-header">
          <h2>Manage workspaces</h2>
          <button className="file-ingest-btn secondary" onClick={onClose}>
            Close
          </button>
        </div>
        {error && <div className="explore-error">{error}</div>}
        <div className="workspace-manage-list">
          {workspaces.map((ws) => (
            <div
              key={ws.workspace_id}
              className={`workspace-manage-row ${ws.workspace_id === currentId ? 'current' : ''}`}
            >
              {renamingId === ws.workspace_id ? (
                <div className="workspace-manage-rename-form">
                  <input
                    value={renameName}
                    onChange={(e) => setRenameName(e.target.value)}
                    autoFocus
                    placeholder="Workspace name"
                  />
                  <input
                    value={renameDesc}
                    onChange={(e) => setRenameDesc(e.target.value)}
                    placeholder="Description (optional)"
                  />
                  <button
                    className="file-ingest-btn"
                    disabled={busyId === ws.workspace_id || !renameName.trim()}
                    onClick={() => submitRename(ws.workspace_id)}
                  >
                    Save
                  </button>
                  <button className="file-ingest-btn secondary" onClick={() => setRenamingId(null)}>
                    Cancel
                  </button>
                </div>
              ) : (
                <>
                  <div className="workspace-manage-info">
                    <div className="workspace-manage-name">
                      {ws.name}
                      {ws.workspace_id === currentId && <span className="workspace-manage-badge">current</span>}
                    </div>
                    <div className="workspace-manage-meta">
                      {ws.source_count} source{ws.source_count === 1 ? '' : 's'} · {ws.relationship_count} relationship
                      {ws.relationship_count === 1 ? '' : 's'}
                      {ws.description ? ` · ${ws.description}` : ''}
                    </div>
                  </div>
                  <div className="workspace-manage-actions">
                    {ws.workspace_id !== currentId && (
                      <button className="file-ingest-btn secondary" onClick={() => onSwitch(ws.workspace_id)}>
                        Switch
                      </button>
                    )}
                    <button className="file-ingest-btn secondary" onClick={() => startRename(ws)}>
                      Rename
                    </button>
                    <button className="file-ingest-btn secondary" onClick={() => onSaveAs(ws)}>
                      Save as…
                    </button>
                    {confirmDeleteId === ws.workspace_id ? (
                      <>
                        <span className="workspace-manage-confirm-text">Delete permanently?</span>
                        <button
                          className="file-ingest-btn danger"
                          disabled={busyId === ws.workspace_id}
                          onClick={() => submitDelete(ws.workspace_id)}
                        >
                          Confirm delete
                        </button>
                        <button className="file-ingest-btn secondary" onClick={() => setConfirmDeleteId(null)}>
                          Cancel
                        </button>
                      </>
                    ) : (
                      <button
                        className="file-ingest-btn danger"
                        onClick={() => {
                          setConfirmDeleteId(ws.workspace_id)
                          setRenamingId(null)
                        }}
                      >
                        Delete
                      </button>
                    )}
                  </div>
                </>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
