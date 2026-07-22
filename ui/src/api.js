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
  ontology: () => request('/v1/ontology'),
  explore: () => request('/v1/explore'),
  ingestFile: (filename, content, sourceSystem, principal = DEFAULT_PRINCIPAL) =>
    request('/v1/explore/ingest', {
      method: 'POST',
      body: { filename, content, source_system: sourceSystem, principal },
    }),
  profile: (source, principal = DEFAULT_PRINCIPAL) =>
    request(`/v1/explore/profile?source=${encodeURIComponent(source)}&principal=${encodeURIComponent(principal)}`),
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
}
