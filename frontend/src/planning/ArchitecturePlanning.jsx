import { Blocks, Download, FileCode2, PencilRuler, Plus, Save, ServerCog, Sparkles, Trash2 } from 'lucide-react'
import mermaid from 'mermaid'
import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import DockablePanel from '../components/DockablePanel'
import DiagramStudio from './DiagramStudio'
import PlanningDialog from './PlanningDialog'

mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'base', themeVariables: { primaryColor: '#d3e3fd', primaryTextColor: '#1f1f1f', primaryBorderColor: '#0b57d0', lineColor: '#5f6368', secondaryColor: '#e6f4ea', tertiaryColor: '#fef7e0', fontFamily: 'Roboto, sans-serif' } })

const TEMPLATES = {
  architecture: `flowchart LR
    Web["Web application"] --> API["Experience API"]
    API --> Domain["Domain services"]
    Domain --> Data[("Operational data")]
    Domain -. events .-> Bus{{"Event bus"}}
    Bus --> Analytics["Analytics platform"]`,
  infrastructure: `flowchart TB
    User(("User")) --> Edge["CDN / WAF"]
    Edge --> LB["Load balancer"]
    subgraph cloud["Production cloud"]
      LB --> App1["App instance A"]
      LB --> App2["App instance B"]
      App1 --> DB[("Managed database")]
      App2 --> DB
      App1 --> Cache[("Cache")]
      App2 --> Cache
    end`,
}

function MermaidPreview({ source, onError, svgRef }) {
  const container = useRef(null)
  useEffect(() => {
    let active = true
    const render = async () => {
      try {
        const id = `l1-mermaid-${Date.now()}-${Math.random().toString(16).slice(2)}`
        const { svg, bindFunctions } = await mermaid.render(id, source)
        if (!active || !container.current) return
        container.current.innerHTML = svg
        bindFunctions?.(container.current)
        svgRef.current = svg
        onError(null)
      } catch (error) {
        if (active) onError(error)
      }
    }
    const timer = setTimeout(render, 220)
    return () => { active = false; clearTimeout(timer) }
  }, [source, onError, svgRef])
  return <div ref={container} className="l1-mermaid-preview" />
}

export default function ArchitecturePlanning({ projectId, l1Id, plan, refresh, setError }) {
  const [selectedId, setSelectedId] = useState(plan.diagrams[0]?.id || null)
  const selected = plan.diagrams.find((item) => item.id === selectedId) || plan.diagrams[0] || null
  const [draft, setDraft] = useState(null)
  const [previewError, setPreviewError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [studioOpen, setStudioOpen] = useState(false)
  const [savingStudio, setSavingStudio] = useState(false)
  const [promptOpen, setPromptOpen] = useState(false)
  const [promptText, setPromptText] = useState('')
  const [promptType, setPromptType] = useState('architecture')
  const [generating, setGenerating] = useState(false)
  const svgRef = useRef('')

  // Re-sync the inline draft when a different diagram is selected AND when the
  // selected diagram's saved version changes (e.g. after the studio saves), so
  // the inline source + preview reflect edits made in the studio.
  useEffect(() => {
    if (selected) setDraft({ title: selected.title, diagram_type: selected.diagram_type, mermaid_source: selected.mermaid_source })
    else setDraft(null)
  }, [selected?.id, selected?.updated_at])

  const choose = (diagram) => { setSelectedId(diagram.id); setPreviewError(null) }
  const create = async (type) => {
    setBusy(true)
    try {
      const created = await api.createDiagram(projectId, l1Id, { diagram_type: type, title: type === 'architecture' ? 'Solution architecture' : 'Infrastructure topology', mermaid_source: TEMPLATES[type] })
      await refresh(); setSelectedId(created.id)
    } catch (error) { setError(error) } finally { setBusy(false) }
  }
  const save = async () => {
    if (!selected || previewError) return
    setBusy(true)
    try { await api.updateDiagram(projectId, selected.id, draft); await refresh() }
    catch (error) { setError(error) } finally { setBusy(false) }
  }
  const remove = async () => {
    if (!selected || !window.confirm(`Delete diagram "${selected.title}"?`)) return
    try { await api.deleteDiagram(projectId, selected.id); setSelectedId(null); await refresh() } catch (error) { setError(error) }
  }
  const saveFromStudio = async (payload) => {
    if (!selected) return
    setSavingStudio(true)
    try { await api.updateDiagram(projectId, selected.id, payload); await refresh() }
    catch (error) { setError(error) } finally { setSavingStudio(false) }
  }
  const generate = async () => {
    if (!promptText.trim()) return
    setGenerating(true)
    try {
      const created = await api.generateDiagram(projectId, l1Id, { prompt: promptText.trim(), diagram_type: promptType })
      setPromptOpen(false); setPromptText('')
      await refresh()
      setSelectedId(created.id)
      setStudioOpen(true)
    } catch (error) { setError(error) } finally { setGenerating(false) }
  }
  const assist = (payload) => api.assistDiagram(projectId, l1Id, payload)
  const downloadSvg = () => {
    if (!svgRef.current) return
    const blob = new Blob([svgRef.current], { type: 'image/svg+xml' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = `${draft.title.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}.svg`; anchor.click()
    URL.revokeObjectURL(url)
  }
  const dirty = selected && draft && (draft.title !== selected.title || draft.diagram_type !== selected.diagram_type || draft.mermaid_source !== selected.mermaid_source)

  return <section>
    <div className="l1-section-heading">
      <div><h2>Architecture & infrastructure</h2><p>Edit Mermaid source and see the system view update live. Diagrams remain portable, reviewable, and version-control friendly.</p></div>
      <div className="l1-heading-actions">
        <button className="m3-btn tonal small" disabled={busy} onClick={() => { setPromptType('architecture'); setPromptOpen(true) }}><Sparkles size={15} /> Generate with AI</button>
        <button className="m3-btn outlined small" disabled={busy} onClick={() => create('infrastructure')}><ServerCog size={15} /> Infrastructure</button>
        <button className="m3-btn filled small" disabled={busy} onClick={() => create('architecture')}><Plus size={15} /> Architecture</button>
      </div>
    </div>

    {plan.diagrams.length === 0
      ? <div className="l1-empty-panel"><Blocks size={32} /><h3>Create a living technical view</h3><p>Describe the system in plain language and let AI draft it, or start from a Mermaid template — then edit the source and visual view live.</p><div className="l1-heading-actions"><button className="m3-btn tonal" onClick={() => { setPromptType('architecture'); setPromptOpen(true) }}><Sparkles size={16} /> Generate with AI</button><button className="m3-btn outlined" onClick={() => create('infrastructure')}><ServerCog size={16} /> Infrastructure</button><button className="m3-btn filled" onClick={() => create('architecture')}><Plus size={16} /> Architecture</button></div></div>
      : <div className="l1-diagram-layout">
        <DockablePanel id="l1-diagram-list" side="left" title="Saved views" defaultWidth={220} minWidth={170} maxWidth={360}>
          <aside className="l1-diagram-list">
            <span className="l1-eyebrow">Saved views</span>
            {plan.diagrams.map((diagram) => <button key={diagram.id} className={selected?.id === diagram.id ? 'active' : ''} onClick={() => choose(diagram)}><span className={`l1-unit-mark ${diagram.diagram_type}`}><FileCode2 size={16} /></span><span><strong>{diagram.title}</strong><small>{diagram.diagram_type} · {new Date(diagram.updated_at).toLocaleDateString()}</small></span></button>)}
          </aside>
        </DockablePanel>
        {draft && <div className="l1-diagram-studio">
          <header className="l1-studio-toolbar">
            <label><span>Diagram name</span><input value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} /></label>
            <label><span>View</span><select value={draft.diagram_type} onChange={(event) => setDraft({ ...draft, diagram_type: event.target.value })}><option value="architecture">Architecture</option><option value="infrastructure">Infrastructure</option></select></label>
            <span className="l1-save-state">{dirty ? 'Unsaved changes' : 'Saved'}</span>
            <button className="m3-btn tonal small" onClick={() => setStudioOpen(true)}><PencilRuler size={15} /> Open studio</button>
            <button className="m3-btn text small" onClick={downloadSvg} disabled={!!previewError}><Download size={15} /> SVG</button>
            <button className="m3-btn filled small" onClick={save} disabled={busy || !dirty || !!previewError || !draft.title.trim()}><Save size={15} /> Save</button>
            <button className="m3-icon-btn danger-ink" onClick={remove} aria-label="Delete diagram"><Trash2 size={17} /></button>
          </header>
          <div className="l1-studio-body">
            <div className="l1-code-pane"><header><FileCode2 size={15} /> Mermaid source</header><textarea spellCheck="false" value={draft.mermaid_source} onChange={(event) => setDraft({ ...draft, mermaid_source: event.target.value })} aria-label="Mermaid diagram source" /></div>
            <div className="l1-preview-pane"><header><Blocks size={15} /> Live preview</header>{previewError && <div className="l1-diagram-error"><strong>Diagram needs attention</strong><span>{String(previewError.message || previewError).split('\n')[0]}</span></div>}<MermaidPreview source={draft.mermaid_source} svgRef={svgRef} onError={setPreviewError} /></div>
          </div>
        </div>}
      </div>}

    {studioOpen && selected && <DiagramStudio key={selected.id} diagram={selected} saving={savingStudio}
      onSave={saveFromStudio} onAssist={assist} onClose={() => setStudioOpen(false)} />}

    {promptOpen && <PlanningDialog
      title="Generate a diagram with AI"
      onClose={() => setPromptOpen(false)}
      actions={<>
        <button className="m3-btn text" onClick={() => setPromptOpen(false)}>Cancel</button>
        <button className="m3-btn filled" disabled={generating || !promptText.trim()} onClick={generate}><Sparkles size={15} /> {generating ? 'Generating…' : 'Generate'}</button>
      </>}>
      <label className="m3-field"><span>View</span>
        <select value={promptType} onChange={(event) => setPromptType(event.target.value)}>
          <option value="architecture">Architecture</option>
          <option value="infrastructure">Infrastructure</option>
        </select></label>
      <label className="m3-field"><span>Describe the system or requirement</span>
        <textarea autoFocus rows={5} value={promptText} onChange={(event) => setPromptText(event.target.value)}
          placeholder="e.g. A React web app calls an experience API, which uses domain services backed by PostgreSQL and publishes events to Kafka for an analytics platform." /></label>
      <p className="req-dialog-note">The assistant drafts an editable Mermaid flowchart. You can refine it in the studio — by text, visually, or by chatting.</p>
    </PlanningDialog>}
  </section>
}
