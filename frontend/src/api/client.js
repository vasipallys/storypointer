const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '')

async function jsonRequest(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options)
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = body.error || body.detail || body
    const error = new Error(detail.message || `Request failed (${response.status})`)
    error.payload = detail
    throw error
  }
  return body
}

export async function consumeSSE(path, payload, onEvent, signal) {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(payload),
    signal,
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    const detail = body.error || body.detail || body
    const error = new Error(detail.message || `Request failed (${response.status})`)
    error.payload = detail
    throw error
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
    const blocks = buffer.split(/\r?\n\r?\n/)
    buffer = blocks.pop() || ''
    for (const block of blocks) {
      let event = 'message'
      const data = []
      for (const line of block.split(/\r?\n/)) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        if (line.startsWith('data:')) data.push(line.slice(5).trim())
      }
      if (data.length) onEvent(event, JSON.parse(data.join('\n')))
    }
    if (done) break
  }
}

export const api = {
  config: () => jsonRequest('/config'),
  health: () => jsonRequest('/health'),
  jiraInstances: () => jsonRequest('/jira/instances'),
  jiraIssues: (instance, project, filters = {}) => {
    const query = new URLSearchParams(Object.entries(filters).filter(([, value]) => value))
    return jsonRequest(`/jira/${encodeURIComponent(instance)}/project/${encodeURIComponent(project)}/issues?${query}`)
  },
  parseUpload: async (file) => {
    const form = new FormData()
    form.append('file', file)
    return jsonRequest('/upload/parse', { method: 'POST', body: form })
  },
  estimate: (story, onEvent, signal, sessionId, refinement) =>
    consumeSSE('/estimate', { story, session_id: sessionId, refinement }, onEvent, signal),
  estimateBatch: (stories, onEvent, signal) =>
    consumeSSE('/estimate/batch', { stories }, onEvent, signal),
  estimateUpload: (rows, mapping, onEvent, signal) =>
    consumeSSE('/upload/estimate', { rows, mapping }, onEvent, signal),
  writePoints: (instance, key, points) =>
    jsonRequest(`/jira/${encodeURIComponent(instance)}/${encodeURIComponent(key)}/points`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ points, confirm: true }),
    }),
  templateUrl: `${API_BASE}/upload/template`,

  listProjects: () => jsonRequest('/projects'),
  createProject: (payload) => json('/projects', 'POST', payload),
  getProject: (id) => jsonRequest(`/projects/${id}`),
  deleteProject: (id) => jsonRequest(`/projects/${id}`, { method: 'DELETE' }),
  addRepo: (id, payload) => json(`/projects/${id}/repos`, 'POST', payload),
  addJiraLink: (id, payload) => json(`/projects/${id}/jira`, 'POST', payload),

  c4Graph: (id) => jsonRequest(`/projects/${id}/c4/graph`),
  createElement: (id, payload) => json(`/projects/${id}/c4/elements`, 'POST', payload),
  updateElement: (id, elementId, payload) => json(`/projects/${id}/c4/elements/${elementId}`, 'PATCH', payload),
  deleteElement: (id, elementId) => jsonRequest(`/projects/${id}/c4/elements/${elementId}`, { method: 'DELETE' }),
  createRelation: (id, payload) => json(`/projects/${id}/c4/relations`, 'POST', payload),
  deleteRelation: (id, relationId) => jsonRequest(`/projects/${id}/c4/relations/${relationId}`, { method: 'DELETE' }),
  tagElement: (id, elementId, payload) => json(`/projects/${id}/c4/elements/${elementId}/tag`, 'POST', payload),
  importRepoScan: (id, payload) => json(`/projects/${id}/c4/import/repo-scan`, 'POST', payload),
  importJira: (id, payload = {}) => json(`/projects/${id}/c4/import/jira`, 'POST', payload),
  rollup: (id) => jsonRequest(`/projects/${id}/rollup`),
  createArtifact: (id, elementId, payload) => json(`/projects/${id}/elements/${elementId}/artifact`, 'POST', payload),
  estimateElement: (id, elementId, payload, onEvent, signal) =>
    consumeSSE(`/projects/${id}/elements/${elementId}/estimate`, payload, onEvent, signal),
}

function json(path, method, payload) {
  return jsonRequest(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}
