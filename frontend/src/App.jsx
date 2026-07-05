import { BrainCircuit, Server } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from './api/client'
import NewProjectWizard from './screens/NewProjectWizard'
import ProjectsHome from './screens/ProjectsHome'
import ProjectWorkspace from './screens/ProjectWorkspace'
import QuickEstimate from './screens/QuickEstimate'

export default function App() {
  const [route, setRoute] = useState({ name: 'home' })
  const [config, setConfig] = useState(null)
  const [health, setHealth] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    Promise.all([api.config(), api.health()])
      .then(([nextConfig, nextHealth]) => { setConfig(nextConfig); setHealth(nextHealth) })
      .catch(setError)
  }, [])

  const jiraStatuses = health?.jira ? Object.entries(health.jira) : []
  const configurationError = health?.llm?.errors?.length
    ? `Backend configuration: ${health.llm.errors.join('; ')}`
    : error ? String(error.message || error) : null

  return <div className="m3 app-shell">
    <header className="m3-topbar">
      <button className="m3-brand" onClick={() => setRoute({ name: 'home' })} aria-label="Story Pointer home">
        <span className="m3-brand-mark"><BrainCircuit size={20} /></span>
        <span style={{ textAlign: 'left' }}><strong>Story Pointer</strong><small>C4 workspace · evidence-led estimation</small></span>
      </button>
      <div className="m3-topbar-status">
        <span className="m3-chip"><Server size={13} />{config ? (config.llm.provider ? `${config.llm.provider} · ${config.llm.model}` : 'LLM not configured') : 'Checking model…'}</span>
        {jiraStatuses.map(([name, value]) => <span key={name} className={`m3-chip ${value.status === 'ok' ? 'ok' : 'bad'}`}>{name}</span>)}
      </div>
    </header>
    {route.name === 'project'
      ? <>
        {configurationError && <div className="m3-content" style={{ padding: '16px 28px 0' }}><div className="m3-banner error">{configurationError}</div></div>}
        <ProjectWorkspace key={route.id} projectId={route.id} config={config} notice={route.notice} />
      </>
      : <div className="m3-content" style={{ flex: 1 }}>
        {configurationError && <div className="m3-banner error">{configurationError}</div>}
        {route.name === 'home' && <ProjectsHome
          onOpen={(id) => setRoute({ name: 'project', id })}
          onNew={() => setRoute({ name: 'wizard' })}
          onQuick={() => setRoute({ name: 'quick' })} />}
        {route.name === 'wizard' && <NewProjectWizard config={config}
          onDone={(id, notice) => setRoute({ name: 'project', id, notice })}
          onCancel={() => setRoute({ name: 'home' })} />}
        {route.name === 'quick' && <>
          <div className="m3-page-title"><h1>Quick estimate</h1><p>One-off estimation without a project — form, Jira browse, or spreadsheet.</p></div>
          <QuickEstimate config={config} />
        </>}
      </div>}
  </div>
}
