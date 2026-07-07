import { Trash2, UserPlus } from 'lucide-react'

/**
 * Add / remove / edit the people accountable for a platform.
 * `leads` is a list of { name, role }; `onChange` receives the next list.
 */
export default function LeadsEditor({ leads, onChange }) {
  const update = (index, key, value) => onChange(leads.map((lead, i) => (i === index ? { ...lead, [key]: value } : lead)))
  const add = () => onChange([...leads, { name: '', role: '' }])
  const remove = (index) => onChange(leads.filter((_, i) => i !== index))

  return (
    <div className="leads-editor">
      {leads.length === 0 && <p className="leads-empty">No leads yet — add the people accountable for this platform.</p>}
      {leads.map((lead, index) => (
        <div key={index} className="leads-row">
          <input value={lead.name} placeholder="Lead name" aria-label="Lead name" onChange={(event) => update(index, 'name', event.target.value)} />
          <input value={lead.role || ''} placeholder="Role (optional)" aria-label="Lead role" onChange={(event) => update(index, 'role', event.target.value)} />
          <button type="button" className="m3-icon-btn small" onClick={() => remove(index)} aria-label="Remove lead"><Trash2 size={15} /></button>
        </div>
      ))}
      <button type="button" className="m3-btn text small" onClick={add}><UserPlus size={15} /> Add lead</button>
    </div>
  )
}
