// Bidirectional bridge between Mermaid flowchart text and an editable graph model.
//
// The model is the contract shared by the text editor, the visual (React Flow)
// editor, and the properties inspector:
//   { direction, nodes: [{id,label,shape}], edges: [{id,source,target,type,label}],
//     groups: [{id,title,members:[nodeId]}], supported }
//
// Only flowcharts round-trip through the visual editor. Other diagram types
// (sequence, class, …) parse as `supported: false` so callers can fall back to
// text-only editing without destroying the source.

export const NODE_SHAPES = [
  { id: 'rect', label: 'Rectangle', open: '[', close: ']' },
  { id: 'round', label: 'Rounded', open: '(', close: ')' },
  { id: 'stadium', label: 'Stadium', open: '([', close: '])' },
  { id: 'subroutine', label: 'Subroutine', open: '[[', close: ']]' },
  { id: 'cylinder', label: 'Database', open: '[(', close: ')]' },
  { id: 'circle', label: 'Circle', open: '((', close: '))' },
  { id: 'diamond', label: 'Decision', open: '{', close: '}' },
  { id: 'hexagon', label: 'Hexagon', open: '{{', close: '}}' },
  { id: 'parallelogram', label: 'Data', open: '[/', close: '/]' },
]

export const EDGE_TYPES = [
  { id: 'arrow', label: 'Arrow', plain: '-->', mid: (t) => `-- ${t} -->` },
  { id: 'open', label: 'Line', plain: '---', mid: (t) => `-- ${t} ---` },
  { id: 'dotted', label: 'Dotted', plain: '-.->', mid: (t) => `-. ${t} .->` },
  { id: 'thick', label: 'Thick', plain: '==>', mid: (t) => `== ${t} ==>` },
]

export const DIRECTIONS = [
  { id: 'LR', label: 'Left → Right' },
  { id: 'TB', label: 'Top → Bottom' },
  { id: 'RL', label: 'Right → Left' },
  { id: 'BT', label: 'Bottom → Top' },
]

const SHAPE_BY_ID = Object.fromEntries(NODE_SHAPES.map((shape) => [shape.id, shape]))
// Match most specific (two-char) wrappers before generic single-char ones.
const SHAPE_MATCH_ORDER = ['subroutine', 'cylinder', 'circle', 'parallelogram', 'stadium', 'hexagon', 'rect', 'round', 'diamond']

// Endpoint = id plus an optional shape wrapper. Non-greedy bodies stop at the
// first matching close so `Data[("x")]` and `Bus{{"y"}}` parse correctly.
const ENDPOINT_SRC =
  '([A-Za-z0-9_]+)\\s*' +
  '(\\[\\[[\\s\\S]*?\\]\\]|\\[\\([\\s\\S]*?\\)\\]|\\(\\([\\s\\S]*?\\)\\)|\\[\\/[\\s\\S]*?\\/\\]|' +
  '\\(\\[[\\s\\S]*?\\]\\)|\\{\\{[\\s\\S]*?\\}\\}|\\[[\\s\\S]*?\\]|\\([\\s\\S]*?\\)|\\{[\\s\\S]*?\\})?'

const OP_BY_TOKEN = { '-->': 'arrow', '---': 'open', '-.->': 'dotted', '==>': 'thick' }

function stripQuotes(text) {
  const trimmed = text.trim()
  if (trimmed.length >= 2 && ((trimmed[0] === '"' && trimmed.at(-1) === '"') || (trimmed[0] === "'" && trimmed.at(-1) === "'"))) {
    return trimmed.slice(1, -1)
  }
  return trimmed
}

function unwrapShape(wrapper) {
  if (!wrapper) return { shape: 'rect', label: null }
  for (const id of SHAPE_MATCH_ORDER) {
    const { open, close } = SHAPE_BY_ID[id]
    if (wrapper.startsWith(open) && wrapper.endsWith(close) && wrapper.length >= open.length + close.length) {
      return { shape: id, label: stripQuotes(wrapper.slice(open.length, wrapper.length - close.length)) }
    }
  }
  return { shape: 'rect', label: null }
}

// Rewrite the three "middle text" edge forms into the uniform pipe form so the
// scanner only has to handle `OP` optionally followed by `|label|`.
function normalizeEdgeLabels(line) {
  return line
    .replace(/--\s+([^|>]+?)\s+-->/g, '-->|$1|')
    .replace(/-\.\s+([^|>]+?)\s+\.->/g, '-.->|$1|')
    .replace(/==\s+([^|>]+?)\s+==>/g, '==>|$1|')
    .replace(/--\s+([^|>]+?)\s+---/g, '---|$1|')
}

function looksLikeEdge(line) {
  return /-->|---|-\.->|==>|-\.\s|==\s|--\s/.test(line)
}

export function parseFlowchart(text) {
  const model = { direction: 'LR', nodes: [], edges: [], groups: [], supported: true }
  const source = String(text ?? '')
  const rawLines = source.split('\n')

  const nodeMap = new Map()
  const groupMap = new Map()
  const groupStack = []
  let edgeSeq = 0
  let sawHeader = false

  const registerNode = (id, wrapper) => {
    const { shape, label } = unwrapShape(wrapper)
    let node = nodeMap.get(id)
    if (!node) {
      node = { id, label: label ?? id, shape: shape || 'rect' }
      nodeMap.set(id, node)
    } else if (wrapper) {
      node.shape = shape || node.shape
      if (label != null) node.label = label
    }
    const group = groupStack.at(-1)
    if (group && !group.members.includes(id)) group.members.push(id)
    return id
  }

  for (const raw of rawLines) {
    const line = raw.trim()
    if (!line) continue
    if (line.startsWith('%%')) continue

    if (!sawHeader) {
      const header = line.match(/^(flowchart|graph)\s+(TB|TD|BT|RL|LR)\b/i)
      if (header) {
        const dir = header[2].toUpperCase()
        model.direction = dir === 'TD' ? 'TB' : dir
        sawHeader = true
        continue
      }
      // First meaningful line is not a flowchart header → unsupported for visual editing.
      if (/^(sequenceDiagram|classDiagram|stateDiagram|erDiagram|journey|gantt|pie|mindmap|timeline|gitGraph|quadrantChart|C4Context)/i.test(line)) {
        model.supported = false
        return model
      }
      if (/^(flowchart|graph)\b/i.test(line)) { sawHeader = true; continue }
    }

    // Styling / class directives are preserved by the text editor but ignored by the model.
    if (/^(classDef|class |style |linkStyle|click |direction )/i.test(line)) continue

    const subgraph = line.match(/^subgraph\s+(?:([A-Za-z0-9_]+)\s*)?(?:\[?"?([^"\]]*)"?\]?)?\s*$/i)
    if (line.toLowerCase().startsWith('subgraph')) {
      const id = subgraph?.[1] || `group${groupMap.size + 1}`
      const title = stripQuotes(subgraph?.[2] || '') || id
      const group = { id, title, members: [] }
      groupMap.set(id, group)
      groupStack.push(group)
      continue
    }
    if (line === 'end') { groupStack.pop(); continue }

    const normalized = normalizeEdgeLabels(line)
    if (looksLikeEdge(normalized)) {
      scanChain(normalized, registerNode, (source, target, type, label) => {
        model.edges.push({ id: `e${edgeSeq++}`, source, target, type, label: label ? label.trim() : '' })
      })
      continue
    }

    // Node-only declaration.
    const nodeOnly = normalized.match(new RegExp(`^${ENDPOINT_SRC}\\s*$`))
    if (nodeOnly) registerNode(nodeOnly[1], nodeOnly[2])
  }

  model.nodes = [...nodeMap.values()]
  model.groups = [...groupMap.values()]
  return model
}

function scanChain(line, registerNode, addEdge) {
  const endpointRe = new RegExp(ENDPOINT_SRC, 'y')
  const opRe = /\s*(-->|-\.->|==>|---)\s*(?:\|([^|]*)\|)?\s*/y

  endpointRe.lastIndex = 0
  let match = endpointRe.exec(line)
  if (!match) return
  let prev = registerNode(match[1], match[2])
  let pos = endpointRe.lastIndex

  while (pos < line.length) {
    opRe.lastIndex = pos
    const op = opRe.exec(line)
    if (!op) break
    pos = opRe.lastIndex
    endpointRe.lastIndex = pos
    const next = endpointRe.exec(line)
    if (!next) break
    const current = registerNode(next[1], next[2])
    addEdge(prev, current, OP_BY_TOKEN[op[1]] || 'arrow', op[2] || '')
    prev = current
    pos = endpointRe.lastIndex
  }
}

function quoteLabel(label) {
  return String(label ?? '').replace(/"/g, '#quot;')
}

function declareNode(node) {
  const shape = SHAPE_BY_ID[node.shape] || SHAPE_BY_ID.rect
  return `${node.id}${shape.open}"${quoteLabel(node.label)}"${shape.close}`
}

function edgeSegment(edge) {
  const type = EDGE_TYPES.find((item) => item.id === edge.type) || EDGE_TYPES[0]
  const connector = edge.label ? type.mid(edge.label) : type.plain
  return `${edge.source} ${connector} ${edge.target}`
}

export function modelToMermaid(model) {
  const direction = DIRECTIONS.some((item) => item.id === model.direction) ? model.direction : 'LR'
  const lines = [`flowchart ${direction}`]
  const declared = new Set()
  const nodeById = new Map(model.nodes.map((node) => [node.id, node]))

  for (const group of model.groups || []) {
    const title = group.title && group.title !== group.id ? `["${quoteLabel(group.title)}"]` : ''
    lines.push(`  subgraph ${group.id}${title}`)
    for (const memberId of group.members || []) {
      const node = nodeById.get(memberId)
      if (node && !declared.has(node.id)) { lines.push(`    ${declareNode(node)}`); declared.add(node.id) }
    }
    lines.push('  end')
  }

  for (const node of model.nodes) {
    if (!declared.has(node.id)) { lines.push(`  ${declareNode(node)}`); declared.add(node.id) }
  }
  for (const edge of model.edges) {
    lines.push(`  ${edgeSegment(edge)}`)
  }
  return lines.join('\n')
}

// Unique, mermaid-safe node id (letters/digits/underscore) for newly added nodes.
export function nextNodeId(model, base = 'node') {
  const taken = new Set(model.nodes.map((node) => node.id))
  let index = model.nodes.length + 1
  let candidate = `${base}${index}`
  while (taken.has(candidate)) { index += 1; candidate = `${base}${index}` }
  return candidate
}
