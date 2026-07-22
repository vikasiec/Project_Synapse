import dagre from '@dagrejs/dagre'

// Shared between ExploreView (one-source-at-a-time fan-out) and SchemaView
// (all-sources-at-once ERD) so both render confirmed/corrected/candidate
// relationships identically instead of duplicating the color/identity logic.

export const STATUS_COLOR = {
  high_confidence: '#34d399',
  candidate: '#5b8cff',
  manual: '#a78bfa',
}
export const CONFIRMED_COLOR = '#22c55e' // solid green -- accepted as-is (SAME_ENTITY_AS)
export const CORRECTED_COLOR = '#f59e0b' // amber -- accepted with a relabeled predicate

export const ROW_H = 26
export const HEADER_H = 34
export const CARD_W = 240
export const GAP_X = 60
export const GAP_Y = 40
export const COLUMNS = 3

// A field pair's identity is (source_system, field_name) on each side,
// order-independent -- NOT candidate_id, which is a fresh UUID minted by
// every /v1/explore/analyze call and therefore useless for recognizing
// "this is the same relationship I already confirmed" across re-analyzes
// or page reloads. This key is what actually persists.
export function relationshipKey(a, b) {
  return [`${a.source_system}::${a.field_name}`, `${b.source_system}::${b.field_name}`].sort().join('|')
}

export function sourceNodeId(sourceSystem) {
  return `src:${sourceSystem}`
}

// Simple masonry default layout for sources with no saved position yet,
// shared so a never-arranged source in SchemaView still lands sensibly
// instead of stacking at (0,0), same as ExploreView's fallback.
export function masonryPosition(index, heights, colHeights) {
  const col = index % COLUMNS
  let target = 0
  for (let c = 1; c < COLUMNS; c++) {
    if (colHeights[c] < colHeights[target]) target = c
  }
  const x = target * (CARD_W + GAP_X) + 20
  const y = colHeights[target] + 20
  colHeights[target] += heights[index] + GAP_Y
  return { x, y }
}

export function estimateCardHeight(fieldCount) {
  return HEADER_H + Math.max(fieldCount, 1) * ROW_H + 16
}

// Graph-aware layout for SchemaView's ERD: nodes connected by a confirmed
// relationship land near each other and ranked left-to-right by the graph
// structure, instead of an arbitrary masonry grid that has no relation to
// what's actually connected to what. Used (a) as the fallback position for
// any source with no saved layout yet, and (b) by the explicit "Reset
// layout" action that recomputes + persists positions for every source --
// the fix for manually-dragged cards drifting to extreme/overlapping
// coordinates over time (dangling-looking edges when a node ends up far
// outside the diagram's natural bounds).
export function computeAutoLayout(sources, profilesBySource, relationships) {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', nodesep: 50, ranksep: 140 })
  g.setDefaultEdgeLabel(() => ({}))

  for (const s of sources) {
    const height = estimateCardHeight((profilesBySource[s.source_system] || []).length)
    g.setNode(sourceNodeId(s.source_system), { width: CARD_W, height })
  }
  for (const r of relationships) {
    const a = sourceNodeId(r.source_a.source_system)
    const b = sourceNodeId(r.source_b.source_system)
    if (g.hasNode(a) && g.hasNode(b)) g.setEdge(a, b)
  }

  dagre.layout(g)

  const positions = {}
  for (const s of sources) {
    const id = sourceNodeId(s.source_system)
    const node = g.node(id)
    if (!node) continue
    // dagre positions are node-center; ReactFlow positions are top-left.
    positions[s.source_system] = { x: node.x - node.width / 2, y: node.y - node.height / 2 }
  }
  return positions
}
