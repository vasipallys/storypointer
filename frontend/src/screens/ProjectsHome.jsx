import { FolderGit2, Plus, Trash2, Zap } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../api/client'

export default function ProjectsHome({ onOpen, onNew, onQuick }) {
  const [projects, setProjects] = useState(null)
  const [error, setError] = useState(null)

  const refresh = () => api.listProjects().then(setProjects).catch(setError)
  useEffect(() => { refresh() }, [])

  const remove = async (event, project) => {
    event.stopPropagation()
    if (!window.confirm(`Delete project "${project.name}" and its whole C4 model? This cannot be undone.`)) return
    try { await api.deleteProject(project.id); refresh() } catch (err) { setError(err) }
  }

  return <div>
    <div className="m3-page-title">
      <h1>Projects</h1>
      <p>Each project links a code repo and a Jira project to one C4 model.</p>
      <span style={{ flex: 1 }} />
      <button className="m3-btn text" onClick={onQuick}><Zap size={16} /> Quick estimate</button>
    </div>
    {error && <div className="m3-banner error">{String(error.message || error)}</div>}
    {projects && projects.length === 0 && <div className="m3-empty">
      <h2>No projects yet</h2>
      <p>Create one to model your system as C4 and estimate from the architecture,<br />or use Quick estimate for a one-off story.</p>
    </div>}
    <div className="m3-grid">
      {(projects || []).map((project) => <div key={project.id} className="m3-card clickable" onClick={() => onOpen(project.id)}
        role="button" tabIndex={0} onKeyDown={(event) => event.key === 'Enter' && onOpen(project.id)}>
        <h3>{project.name}</h3>
        <div className="m3-meta">{project.description || 'No description'}</div>
        <div className="m3-card-chips">
          {project.repos.length > 0 && <span className="m3-chip"><FolderGit2 size={13} /> {project.repos.length} repo{project.repos.length > 1 ? 's' : ''}</span>}
          {project.jira.map((link) => <span key={link.id} className="m3-chip filled">{link.instance_name} · {link.project_key}</span>)}
          <span className="m3-chip">{project.estimated_count}/{project.story_count} stories estimated</span>
          <button className="m3-btn text small" onClick={(event) => remove(event, project)} aria-label={`Delete ${project.name}`}><Trash2 size={14} /></button>
        </div>
      </div>)}
    </div>
    <button className="m3-fab" onClick={onNew}><Plus size={20} /> New project</button>
  </div>
}
