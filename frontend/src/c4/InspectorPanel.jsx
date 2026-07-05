import { Bug, ExternalLink, Eye, Save, Sparkles, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../api/client'

const ARTIFACT_LABEL = { initiative: 'Theme / initiative', epic: 'Epic', story: 'Story / feature', task: 'Task / sub-task', bug: 'Bug', tech_debt: 'Tech debt', arch_flow: 'Architecture flow' }
const LEVEL_ARTIFACT = { L1: 'initiative', L2: 'epic', L3: 'story', L4: 'task' }

export default function InspectorPanel({ projectId, element, config, hasCachedResult, onEstimate, onChanged, onDeleted }) {
  const [description, setDescription] = useState('')
  const [error, setError] = useState(null)

  useEffect(() => {
    setDescription(element?.description || '')
    setError(null)
  }, [element?.id])

  if (!element) {
    return <aside className="m3-inspector"><div className="m3-empty" style={{ padding: '40px 10px' }}>
      <h2>Nothing selected</h2>
      <p>Click a node to inspect it, double-click to drill in,<br />drag from a node edge to another node to draw a relation.</p>
    </div></aside>
  }

  const estimable = element.level === 'L3' || element.level === 'L4'
  const artifacts = element.artifacts || []
  const estimated = artifacts.find((item) => item.points != null)

  const saveDescription = () => api.updateElement(projectId, element.id, { description }).then(onChanged).catch(setError)
  const acceptProposed = () => api.updateElement(projectId, element.id, { status: 'active' }).then(onChanged).catch(setError)
  const remove = () => {
    if (!window.confirm(`Delete "${element.name}" and everything nested under it?`)) return
    api.deleteElement(projectId, element.id).then(onDeleted).catch(setError)
  }
  const tagBug = () => api.tagElement(projectId, element.id, { artifact_type: 'bug' }).then(onChanged).catch(setError)
  const createJira = () => {
    if (!window.confirm(`Create a Jira issue for "${element.name}"? This writes to Jira.`)) return
    api.createArtifact(projectId, element.id, { confirm: true })
      .then((response) => { window.alert(`Created ${response.issue_key}`); onChanged() })
      .catch(setError)
  }
  const linkJira = () => {
    const key = window.prompt('Existing Jira issue key to link (for example PAY-42)')
    if (key) api.createArtifact(projectId, element.id, { link_existing_key: key.trim() }).then(onChanged).catch(setError)
  }

  return <aside className="m3-inspector">
    <div className="m3-inspector-header">
      <div>
        <span className={`m3-chip level-${element.level}`}>{element.level} · {ARTIFACT_LABEL[LEVEL_ARTIFACT[element.level]]}</span>
        <h2 style={{ marginTop: 8 }}>{element.name}</h2>
      </div>
      <button className="m3-icon-btn" onClick={remove} aria-label="Delete element"><Trash2 size={17} /></button>
    </div>
    {error && <div className="m3-banner error">{String(error.message || error)}</div>}
    {element.status === 'proposed' && <div className="m3-banner info">Proposed by a scan, import, or estimation — review and accept it.
      <button className="m3-btn tonal small" onClick={acceptProposed}>Accept</button></div>}

    {estimable && <div className="m3-estimate-summary">
      <div>
        <span className="m3-estimate-summary-label">Story points</span>
        <b>{estimated?.points ?? '—'}</b>
        {estimated?.estimated_at && <small>{new Date(estimated.estimated_at).toLocaleString()}</small>}
      </div>
      <div className="m3-estimate-summary-actions">
        {estimated && hasCachedResult && <button className="m3-btn tonal small" onClick={() => onEstimate(element, false)}>
          <Eye size={14} /> View reasoning</button>}
        <button className="m3-btn filled small" onClick={() => onEstimate(element, !estimated)}>
          <Sparkles size={14} /> {estimated ? 'Re-estimate' : 'Estimate'}</button>
      </div>
    </div>}
    {!estimable && <p style={{ color: 'var(--m3-on-surface-variant)', fontSize: 13 }}>
      {element.level} elements are not estimated directly — points roll up from the L3 stories inside (see the Roll-up tab).</p>}

    <dl className="m3-kv">
      {element.tech && <><dt>Tech</dt><dd>{element.tech}</dd></>}
      {element.code_path && <><dt>Code path</dt><dd className="mono">{element.code_path}</dd></>}
      <dt>Status</dt><dd>{element.status}</dd>
      {artifacts.map((artifact) => <span key={artifact.id} style={{ display: 'contents' }}>
        <dt>{ARTIFACT_LABEL[artifact.artifact_type] || artifact.artifact_type}</dt>
        <dd>{artifact.points != null ? `${artifact.points} pts` : '—'}{artifact.jira_issue_key ? ` · ${artifact.jira_issue_key}` : ''}</dd>
      </span>)}
    </dl>
    <label className="m3-field"><span>Description (estimation evidence)</span>
      <textarea rows={4} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
    <div className="m3-inspector-actions">
      <button className="m3-btn text small" onClick={saveDescription} disabled={description === element.description}><Save size={14} /> Save</button>
      {estimable && <button className="m3-btn text small" onClick={tagBug}><Bug size={14} /> Tag bug</button>}
      <button className="m3-btn text small" onClick={linkJira}><ExternalLink size={14} /> Link Jira</button>
      {config?.jira_write_enabled && <button className="m3-btn text small" onClick={createJira}><ExternalLink size={14} /> Create in Jira</button>}
    </div>
  </aside>
}
