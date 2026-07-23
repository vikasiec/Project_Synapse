// Thin fetch wrapper for the synapse/api.py backend. Dev server proxies
// /v1 + /health to the Python process (see vite.config.js); production
// build is served from the same origin by synapse/api.py's static handler.

const DEFAULT_PRINCIPAL = 'l2'

async function request(path, { method = 'GET', body } = {}) {
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const err = new Error(data.error || `${res.status} ${res.statusText}`)
    err.status = res.status
    err.body = data
    throw err
  }
  return data
}

export const api = {
  health: () => request('/health'),
  listWorkspaces: () => request('/v1/workspaces'),
  createWorkspace: (name, description = '') =>
    request('/v1/workspaces', { method: 'POST', body: { name, description } }),
  cloneWorkspace: (workspaceId, name, description = '', principal = DEFAULT_PRINCIPAL) =>
    request(`/v1/workspaces/${encodeURIComponent(workspaceId)}/clone`, {
      method: 'POST',
      body: { name, description, principal },
    }),
  ontology: (workspaceId) =>
    request(workspaceId ? `/v1/ontology?workspace_id=${encodeURIComponent(workspaceId)}` : '/v1/ontology'),
  explore: (workspaceId) =>
    request(workspaceId ? `/v1/explore?workspace_id=${encodeURIComponent(workspaceId)}` : '/v1/explore'),
  ingestFile: (filename, content, sourceSystem, workspaceId, principal = DEFAULT_PRINCIPAL) =>
    request('/v1/explore/ingest', {
      method: 'POST',
      body: { filename, content, source_system: sourceSystem, workspace_id: workspaceId, principal },
    }),
  profile: (source, workspaceId, principal = DEFAULT_PRINCIPAL) =>
    request(
      `/v1/explore/profile?source=${encodeURIComponent(source)}&principal=${encodeURIComponent(principal)}${workspaceId ? `&workspace_id=${encodeURIComponent(workspaceId)}` : ''}`,
    ),
  samples: (source, field, limit = 5, workspaceId, principal = DEFAULT_PRINCIPAL) =>
    request(
      `/v1/explore/samples?source=${encodeURIComponent(source)}&field=${encodeURIComponent(field)}&limit=${limit}&principal=${encodeURIComponent(principal)}${workspaceId ? `&workspace_id=${encodeURIComponent(workspaceId)}` : ''}`,
    ),
  analyze: (sourceA, sourceB, principal = DEFAULT_PRINCIPAL) =>
    request('/v1/explore/analyze', {
      method: 'POST',
      body: sourceB
        ? { source_a: sourceA, source_b: sourceB, principal }
        : { source_a: sourceA, principal },
    }),
  decide: (action, candidateId, extra = {}, principal = DEFAULT_PRINCIPAL) =>
    request('/v1/ontology/relationships', {
      method: 'POST',
      body: { action, candidate_id: candidateId, principal, ...extra },
    }),
  mergeCandidates: (workspaceId, principal = DEFAULT_PRINCIPAL) =>
    request(
      `/v1/er/merge-candidates?principal=${encodeURIComponent(principal)}${workspaceId ? `&workspace_id=${encodeURIComponent(workspaceId)}` : ''}`,
    ),
  mergeEntities: (survivorId, loserId, reason = '', principal = DEFAULT_PRINCIPAL) =>
    request('/v1/entities/merge', {
      method: 'POST',
      body: { survivor_id: survivorId, loser_id: loserId, reason, principal, adjudicator: 'ui:resolve' },
    }),
  reprocess: (principal = DEFAULT_PRINCIPAL) =>
    request('/v1/reprocess', { method: 'POST', body: { principal, actor: 'ui:explore-reprocess' } }),
  dedupeRelationships: (principal = DEFAULT_PRINCIPAL) =>
    request('/v1/ontology/relationships/dedupe', { method: 'POST', body: { principal } }),
  analyzePair: (sourceA, fieldA, sourceB, fieldB, principal = DEFAULT_PRINCIPAL) =>
    request('/v1/explore/analyze', {
      method: 'POST',
      body: { source_a: sourceA, field_a: fieldA, source_b: sourceB, field_b: fieldB, principal },
    }),
  computeSuperSchema: (workspaceIds, principal = DEFAULT_PRINCIPAL) =>
    request('/v1/super-schema', { method: 'POST', body: { workspace_ids: workspaceIds, principal } }),
  previewStarSchema: (workspaceIds, principal = DEFAULT_PRINCIPAL) =>
    request('/v1/materialize/star-schema/preview', { method: 'POST', body: { workspace_ids: workspaceIds, principal } }),
  executeStarSchema: (workspaceIds, targetDbPath, principal = DEFAULT_PRINCIPAL) =>
    request('/v1/materialize/star-schema/execute', {
      method: 'POST',
      body: { workspace_ids: workspaceIds, target_db_path: targetDbPath, principal },
    }),
  getLayout: (workspaceId) =>
    request(workspaceId ? `/v1/schema/layout?workspace_id=${encodeURIComponent(workspaceId)}` : '/v1/schema/layout'),
  saveLayoutPosition: (sourceSystem, x, y, principal = DEFAULT_PRINCIPAL) =>
    request('/v1/schema/layout', {
      method: 'POST',
      body: { source_system: sourceSystem, x, y, principal },
    }),
}
