import { BrainCircuit, ChevronRight, CircleHelp, Server } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from './api/client'
import BatchTable from './components/BatchTable'
import ColumnMapper from './components/ColumnMapper'
import ErrorCard from './components/ErrorCard'
import ExcelUpload from './components/ExcelUpload'
import JiraBrowser from './components/JiraBrowser'
import PipelineView from './components/PipelineView'
import ResultCard from './components/ResultCard'
import SourceSwitcher from './components/SourceSwitcher'
import StatusBadge from './components/StatusBadge'
import StoryForm from './components/StoryForm'

export default function App() {
  const [source, setSource] = useState('manual')
  const [config, setConfig] = useState(null)
  const [health, setHealth] = useState(null)
  const [issues, setIssues] = useState([])
  const [upload, setUpload] = useState(null)
  const [loading, setLoading] = useState(false)
  const [steps, setSteps] = useState([])
  const [pipelineTitle, setPipelineTitle] = useState('')
  const [result, setResult] = useState(null)
  const [results, setResults] = useState([])
  const [error, setError] = useState(null)
  const controller = useRef(null)

  useEffect(() => {
    Promise.all([api.config(), api.health()]).then(([nextConfig, nextHealth]) => { setConfig(nextConfig); setHealth(nextHealth) }).catch(setError)
    return () => controller.current?.abort()
  }, [])

  const begin = () => { setLoading(true); setError(null); setResult(null); setResults([]); setSteps([]); controller.current = new AbortController() }
  const end = () => setLoading(false)
  const onSingleEvent = (event, data) => {
    if (event === 'started') setPipelineTitle(data.title)
    if (event === 'node') setSteps((current) => [...current, data.node])
    if (event === 'result') setResult(data)
    if (event === 'error') setError(new Error(data.message))
  }
  const estimateOne = async (story) => { begin(); try { await api.estimate(story, onSingleEvent, controller.current.signal) } catch (err) { setError(err) } finally { end() } }
  const onBatchEvent = (event, data) => {
    if (event === 'item_started') { setPipelineTitle(data.title); setSteps([]) }
    if (event === 'item_node') setSteps((current) => [...current, data.node])
    if (event === 'item_result') setResults((current) => [...current, data.result])
    if (event === 'item_error' || event === 'error') setError(new Error(data.message))
  }
  const estimateBatch = async (stories) => { begin(); try { await api.estimateBatch(stories, onBatchEvent, controller.current.signal) } catch (err) { setError(err) } finally { end() } }
  const fetchJira = async (instance, project, filters) => { setError(null); setLoading(true); try { setIssues(await api.jiraIssues(instance, project, filters)) } catch (err) { setError(err) } finally { end() } }
  const parseFile = async (file) => { setError(null); setLoading(true); try { setUpload(await api.parseUpload(file)) } catch (err) { setError(err) } finally { end() } }
  const estimateUpload = async (rows, mapping) => { begin(); try { await api.estimateUpload(rows, mapping, onBatchEvent, controller.current.signal) } catch (err) { setError(err) } finally { end() } }
  const writePoints = async (item) => { if (!window.confirm(`Write ${item.points} points to ${item.story.key}? This changes Jira.`)) return; try { await api.writePoints(item.story.jira_instance, item.story.key, item.points); window.alert('Jira was updated.') } catch (err) { setError(err) } }

  const jiraStatuses = health?.jira ? Object.entries(health.jira) : []
  const configurationError = health?.llm?.errors?.length
    ? new Error(`Backend configuration: ${health.llm.errors.join('; ')}`)
    : null
  return <div className="app-shell">
    <header className="topbar"><a className="brand" href="#top" aria-label="Story Pointer home"><span><BrainCircuit size={23} /></span><div><strong>Story Pointer</strong><small>Evidence-led estimation</small></div></a><div className="system-status"><div className="model-badge"><Server size={15} /><span>{config ? (config.llm.provider ? `${config.llm.provider} · ${config.llm.model}` : 'LLM not configured') : 'Checking model...'}</span></div>{jiraStatuses.map(([name, value]) => <StatusBadge key={name} status={value.status}>{name}</StatusBadge>)}</div></header>
    <main id="top"><section className="hero"><div><span className="eyebrow">Defensible by design</span><h1>A point is only useful when<br />everyone understands <em>why.</em></h1><p>Score the real work, calibrate it against your team’s anchors, and share a conclusion a product owner can grasp in five seconds.</p></div><div className="method-card"><CircleHelp size={20} /><div><strong>How it works</strong><ol><li>Score 12 delivery factors</li><li>Find the true drivers</li><li>Compare fixed anchors</li><li>Conclude, never guess</li></ol></div></div></section>
      <SourceSwitcher value={source} onChange={(value) => { setSource(value); setError(null) }} />
      <ErrorCard error={error || configurationError} />
      <div className="workspace">
        <div>{source === 'manual' && <StoryForm onSubmit={estimateOne} disabled={loading} />}{source === 'jira' && <JiraBrowser instances={config?.jira_instances || []} issues={issues} onFetch={fetchJira} onEstimate={estimateBatch} loading={loading} />}{source === 'upload' && (upload ? <ColumnMapper upload={upload} onEstimate={estimateUpload} loading={loading} /> : <ExcelUpload onUpload={parseFile} templateUrl={api.templateUrl} loading={loading} />)}</div>
        <PipelineView steps={steps} active={loading} title={pipelineTitle} />
      </div>
      {results.length > 0 && <BatchTable results={results} onSelect={setResult} />}
      {result && <ResultCard result={result} writeEnabled={config?.jira_write_enabled} onWrite={writePoints} />}
      {!loading && !result && !results.length && <div className="empty-hint"><span>1</span> Add the story <ChevronRight /><span>2</span> Watch the reasoning build <ChevronRight /><span>3</span> Share the justified estimate</div>}
    </main>
    <footer><span>Story Pointer · Reasoning before numbers</span><span>Active model: {config?.llm?.provider || '—'} / {config?.llm?.model || '—'}</span></footer>
  </div>
}
