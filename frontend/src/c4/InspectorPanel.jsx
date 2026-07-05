import { Bug, ExternalLink, Save, Sparkles, Trash2, Wand2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import PipelineView from '../components/PipelineView'
import ResultCard from '../components/ResultCard'

const ARTIFACT_LABEL = { initiative: 'Theme / initiative', epic: 'Epic', story: 'Story / feature', task: 'Task / sub-task', bug: 'Bug', tech_debt: 'Tech debt', arch_flow: 'Architecture flow' }

export default function InspectorPanel({ projectId, element, config, onChanged, onDeleted }) {
  const [description, setDescription] = useState('')
  const [refinement, setRefinement] = useState('')
  const [steps, setSteps] = useState([])
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const controller = useRef(null)

  useEffect(() => {
    setDescription(element?.description || '')
    setResult(null); setSteps([]); setError(null); setRefinement('')
    controller.current?.abort()
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

  const run = async (withRefinement) => {
    setRunning(true); setError(null); setResult(null); setSteps([])
    controller.current = new AbortController()
    try {
      await api.estimateElement(projectId, element.id, { refinement: withRefinement || null }, (event, data) => {
        if (event === 'node') setSteps((current) => [...current, data.node])
        if (event === 'result') setResult(data)
        if (event === 'error') setError(new Error(data.message))
      }, controller.current.signal)
      onChanged()
    } catch (err) { setError(err) } finally { setRunning(false) }
  }

  const saveDescription = () => api.updateElement(projectId, element.id, { description }).then(onChanged).catch(setError)
  const acceptProposed = () => api.updateElement(projectId, element.id, { status: 'active' }).then(onChanged).catch(setError)
  const remove = () => {
    if (!window.confirm(`Delete "${element.name}" and everything nested under it?`)) return
    api.deleteElement(projectId, element.id).then(onDeleted).catch(setError)
  }
  const tagBug = () => api.tagElement(projectId, element.id, { artifact_type: 'bug' }).then(onChanged).catch(setError)
  const createJira = () => {
    if (!window.confirm(`Create a Jira ${element.level === 'L3' ? 'Story' : element.level === 'L4' ? 'Task' : 'Epic'} for "${element.name}"? This writes to Jira.`)) return
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
        <span className={`m3-chip level-${element.level}`}>{element.level} · {ARTIFACT_LABEL[{ L1: 'initiative', L2: 'epic', L3: 'story', L4: 'task' }[element.level]]}</span>
        <h2 style={{ marginTop: 8 }}>{element.name}</h2>
      </div>
      <button className="m3-btn text small" onClick={remove} aria-label="Delete element"><Trash2 size={15} /></button>
    </div>
    {element.status === 'proposed' && <div className="m3-banner info">Proposed by a scan, import, or estimation — review and accept it.
      <button className="m3-btn tonal small" onClick={acceptProposed}>Accept</button></div>}
    <dl className="m3-kv">
      {element.tech && <><dt>Tech</dt><dd>{element.tech}</dd></>}
      {element.code_path && <><dt>Code path</dt><dd className="mono">{element.code_path}</dd></>}
      <dt>Status</dt><dd>{element.status}</dd>
      {artifacts.map((artifact) => <span key={artifact.id} style={{ display: 'contents' }}>
        <dt>{ARTIFACT_LABEL[artifact.artifact_type] || artifact.artifact_type}</dt>
        <dd>{artifact.points != null ? `${artifact.points} pts` : 'not estimated'}{artifact.jira_issue_key ? ` · ${artifact.jira_issue_key}` : ''}</dd>
      </span>)}
    </dl>
    <label className="m3-field"><span>Description (estimation evidence)</span>
      <textarea rows={4} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
    <div className="m3-inspector-actions">
      <button className="m3-btn text small" onClick={saveDescription} disabled={description === element.description}><Save size={14} /> Save</button>
      {(element.level === 'L3' || element.level === 'L4') && <button className="m3-btn text small" onClick={tagBug}><Bug size={14} /> Tag bug</button>}
      <button className="m3-btn text small" onClick={linkJira}><ExternalLink size={14} /> Link Jira</button>
      {config?.jira_write_enabled && <button className="m3-btn text small" onClick={createJira}><ExternalLink size={14} /> Create in Jira</button>}
    </div>
    <hr className="m3-divider" />
    {estimable ? <>
      <div className="m3-inspector-actions">
        <button className="m3-btn filled" onClick={() => run(null)} disabled={running}>
          <Sparkles size={16} /> {running ? 'Estimating…' : estimated ? 'Re-estimate' : 'Estimate'}</button>
      </div>
      {estimated && !running && <>
        <label className="m3-field"><span>Refine the last estimate (same session)</span>
          <input value={refinement} onChange={(event) => setRefinement(event.target.value)}
            placeholder="Re-estimate assuming the rule engine is out of scope" /></label>
        <button className="m3-btn tonal small" onClick={() => run(refinement)} disabled={!refinement.trim()}>
          <Wand2 size={14} /> Refine</button>
      </>}
      {(running || steps.length > 0) && !result && <PipelineView steps={steps} active={running} title={element.name} />}
      {error && <div className="m3-banner error">{String(error.message || error)}</div>}
      {result && <ResultCard result={result} writeEnabled={false} />}
      {result?.hidden_tasks?.length > 0 && <div className="m3-banner info">Hidden tasks were added under this story as proposed L4 elements.</div>}
    </> : <p style={{ color: 'var(--m3-on-surface-variant)', fontSize: 13 }}>
      {element.level} elements are not estimated directly — their points roll up from the L3 stories inside. Open the roll-up tab for the aggregate.</p>}
  </aside>
}
