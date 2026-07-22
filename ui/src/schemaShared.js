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
