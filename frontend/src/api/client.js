const runtimeConfig = typeof window !== 'undefined' ? window.storyPointer : null
const API_BASE = (runtimeConfig?.apiBaseUrl || import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '')

// Local demo auth: identify the caller to the backend RBAC middleware. The
// signed-in user is stored by AuthContext under this key.
const AUTH_KEY = 'storypointer.auth.user'
function authHeaders() {
  try {
    const raw = typeof localStorage !== 'undefined' ? localStorage.getItem(AUTH_KEY) : null
    if (!raw) return {}
    const user = JSON.parse(raw)
    const headers = {}
    if (user?.staff_id) headers['X-User-Id'] = user.staff_id
    if (user?.role) headers['X-User-Role'] = user.role
    return headers
  } catch {
    return {}
  }
}

function withAuth(options = {}) {
  return { ...options, headers: { ...authHeaders(), ...(options.headers || {}) } }
}

async function jsonRequest(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, withAuth(options))
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = body.error || body.detail || body
    const error = new Error(detail.message || `Request failed (${response.status})`)
    error.payload = detail
    throw error
  }
  return body
}

async function downloadRequest(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, withAuth(options))
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    const detail = body.error || body.detail || body
    const error = new Error(detail.message || `Request failed (${response.status})`)
    error.payload = detail
    throw error
  }
  const disposition = response.headers.get('Content-Disposition') || ''
  const filename = disposition.match(/filename="([^"]+)"/i)?.[1] || 'requirements-export'
  return { blob: await response.blob(), filename }
}

export async function consumeSSE(path, payload, onEvent, signal) {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', ...authHeaders() },
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
  updateProject: (id, payload) => json(`/projects/${id}`, 'PATCH', payload),
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

  l1Plan: (id, elementId) => jsonRequest(`/projects/${id}/l1/${elementId}/plan`),
  updateL1Plan: (id, elementId, payload) => json(`/projects/${id}/l1/${elementId}/plan`, 'PATCH', payload),
  createAgileUnit: (id, elementId, payload) => json(`/projects/${id}/l1/${elementId}/units`, 'POST', payload),
  updateAgileUnit: (id, unitId, payload) => json(`/projects/${id}/l1/units/${unitId}`, 'PATCH', payload),
  deleteAgileUnit: (id, unitId) => jsonRequest(`/projects/${id}/l1/units/${unitId}`, { method: 'DELETE' }),
  createTeamMember: (id, unitId, payload) => json(`/projects/${id}/l1/units/${unitId}/members`, 'POST', payload),
  updateTeamMember: (id, memberId, payload) => json(`/projects/${id}/l1/members/${memberId}`, 'PATCH', payload),
  deleteTeamMember: (id, memberId) => jsonRequest(`/projects/${id}/l1/members/${memberId}`, { method: 'DELETE' }),
  createWorkItem: (id, elementId, payload) => json(`/projects/${id}/l1/${elementId}/work`, 'POST', payload),
  updateWorkItem: (id, workItemId, payload) => json(`/projects/${id}/l1/work/${workItemId}`, 'PATCH', payload),
  deleteWorkItem: (id, workItemId) => jsonRequest(`/projects/${id}/l1/work/${workItemId}`, { method: 'DELETE' }),
  createDiagram: (id, elementId, payload) => json(`/projects/${id}/l1/${elementId}/diagrams`, 'POST', payload),
  updateDiagram: (id, diagramId, payload) => json(`/projects/${id}/l1/diagrams/${diagramId}`, 'PATCH', payload),
  deleteDiagram: (id, diagramId) => jsonRequest(`/projects/${id}/l1/diagrams/${diagramId}`, { method: 'DELETE' }),
  generateDiagram: (id, elementId, payload) => json(`/projects/${id}/l1/${elementId}/diagrams/generate`, 'POST', payload),
  assistDiagram: (id, elementId, payload) => json(`/projects/${id}/l1/${elementId}/diagrams/assist`, 'POST', payload),
  listRequirements: (id, elementId) => jsonRequest(`/projects/${id}/l1/${elementId}/requirements`),
  createRequirement: (id, elementId, payload) => json(`/projects/${id}/l1/${elementId}/requirements`, 'POST', payload),
  getRequirement: (id, documentId) => jsonRequest(`/projects/${id}/l1/requirements/${documentId}`),
  getRequirementVersion: (id, documentId, version) => jsonRequest(`/projects/${id}/l1/requirements/${documentId}/versions/${version}`),
  updateRequirement: (id, documentId, payload) => json(`/projects/${id}/l1/requirements/${documentId}`, 'PATCH', payload),
  addRequirementComment: (id, documentId, payload) => json(`/projects/${id}/l1/requirements/${documentId}/comments`, 'POST', payload),
  actOnRequirementComment: (id, commentId, payload) => json(`/projects/${id}/l1/requirements/comments/${commentId}`, 'PATCH', payload),
  reviewRequirement: (id, documentId, payload) => json(`/projects/${id}/l1/requirements/${documentId}/review`, 'POST', payload),
  exportRequirement: (id, documentId, format, payload = {}) => downloadRequest(
    `/projects/${id}/l1/requirements/${documentId}/export/${format}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
  ),

  // Global resource directory — staff pool reusable across modules.
  listStaff: (filters = {}) => {
    const query = new URLSearchParams(Object.entries(filters).filter(([, value]) => value))
    return jsonRequest(`/resources/staff?${query}`)
  },
  getStaff: (staffId) => jsonRequest(`/resources/staff/${staffId}`),
  createStaff: (payload) => json('/resources/staff', 'POST', payload),
  updateStaff: (staffId, payload) => json(`/resources/staff/${staffId}`, 'PATCH', payload),
  deleteStaff: (staffId) => jsonRequest(`/resources/staff/${staffId}`, { method: 'DELETE' }),
  resourceLookups: () => jsonRequest('/resources/lookups'),
  createLookup: (category, payload) => json(`/resources/lookups/${category}`, 'POST', payload),
  updateLookup: (lookupId, payload) => json(`/resources/lookups/${lookupId}`, 'PATCH', payload),
  deleteLookup: (lookupId) => jsonRequest(`/resources/lookups/${lookupId}`, { method: 'DELETE' }),
  listCustomFields: () => jsonRequest('/resources/custom-fields'),
  createCustomField: (payload) => json('/resources/custom-fields', 'POST', payload),
  updateCustomField: (fieldId, payload) => json(`/resources/custom-fields/${fieldId}`, 'PATCH', payload),
  deleteCustomField: (fieldId) => jsonRequest(`/resources/custom-fields/${fieldId}`, { method: 'DELETE' }),

  // Admin — access management (local demo auth) + reporting.
  roles: () => jsonRequest('/access/roles'),
  accessUsers: () => jsonRequest('/access/users'),
  loginUsers: () => jsonRequest('/access/login-users'),
  setAccess: (staffId, payload) => json(`/access/users/${staffId}`, 'PATCH', payload),
  reportingOverview: () => jsonRequest('/reporting/overview'),

  // Agentic AI (Phase 3)
  reportingNarrative: () => json('/reporting/narrative', 'POST', {}),
  aiStaffing: (id, l1Id) => json(`/projects/${id}/l1/${l1Id}/ai/staffing`, 'POST', {}),
  applyStaffing: (id, assignments) => json(`/projects/${id}/ai/staffing/apply`, 'POST', { assignments }),
  aiDecompose: (id, elementId, guidance = '') => json(`/projects/${id}/c4/elements/${elementId}/ai/decompose`, 'POST', { guidance }),
  applyDecompose: (id, elementId, stories) => json(`/projects/${id}/c4/elements/${elementId}/ai/decompose/apply`, 'POST', { stories }),
  aiScaffold: (id, description) => json(`/projects/${id}/c4/ai/scaffold`, 'POST', { description }),
  applyScaffold: (id, payload) => json(`/projects/${id}/c4/ai/scaffold/apply`, 'POST', payload),
}

function json(path, method, payload) {
  return jsonRequest(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}
