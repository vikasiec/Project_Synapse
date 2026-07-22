import { Handle, NodeResizer, Position } from '@xyflow/react'
import './SourceGroupNode.css'

// Renders one landed source as a self-contained structure card: header +
// every observed field with its derived data_type. This is what shows up
// on the canvas automatically for each source. Single-click the header to
// trigger relation discovery against every other loaded source;
// double-click the card (or its "Properties" button) for the full field
// detail (entropy, regex matches, sample count). Resizable via the
// corner/edge handles so a source with many fields can be stretched
// taller instead of scrolling a tiny fixed box.
// An HL7/FHIR source decomposes into virtual sub-sources named
// "base::SEGMENT" (e.g. "new_data_hl7_v2_oru_r01::OBX") -- shown as the
// segment/resourceType name up front (what the card actually is) with the
// base filename as a smaller subtitle, instead of the full string
// truncating illegibly.
function splitVirtualName(sourceSystem) {
  const idx = sourceSystem.indexOf('::')
  if (idx === -1) return { primary: sourceSystem, secondary: null }
  return { primary: sourceSystem.slice(idx + 2), secondary: sourceSystem.slice(0, idx) }
}

export default function SourceGroupNode({ id, data, selected }) {
  const { sourceSystem, fields, active, onActivate, onOpenProperties, fieldHandles } = data
  const { primary, secondary } = splitVirtualName(sourceSystem)

  return (
    <div
      className={`source-node ${active ? 'active' : ''}`}
      onDoubleClick={() => onOpenProperties?.()}
    >
      <NodeResizer minWidth={200} minHeight={90} isVisible={selected} lineStyle={{ borderColor: '#5b8cff' }} handleStyle={{ background: '#5b8cff', width: 8, height: 8 }} />
      {!fieldHandles && (
        <>
          <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
          <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
        </>
      )}
      <div className="source-node-header">
        <button className="source-node-header-btn" onClick={onActivate} title={`Find relations to every other loaded source\n${sourceSystem}`}>
          <span className="source-node-title">
            <span className="source-node-name">{primary}</span>
            {secondary && <span className="source-node-subtitle">{secondary}</span>}
          </span>
          <span className="source-node-count">{fields ? fields.length : '…'} fields</span>
        </button>
        <button className="source-node-props-btn" onClick={() => onOpenProperties?.()} title="Full properties">
          ⓘ
        </button>
      </div>
      <div className="source-node-fields">
        {fields === null && <div className="source-node-loading">Loading structure…</div>}
        {fields && fields.length === 0 && <div className="source-node-loading">No fields detected</div>}
        {fields &&
          fields.map((f) => (
            <div key={f.field_name} className="source-node-row" style={fieldHandles ? { position: 'relative' } : undefined}>
              {fieldHandles && (
                <>
                  <Handle
                    type="target"
                    position={Position.Left}
                    id={`in-${f.field_name}`}
                    style={{ top: '50%', background: '#5b8cff' }}
                  />
                  <Handle
                    type="source"
                    position={Position.Right}
                    id={`out-${f.field_name}`}
                    style={{ top: '50%', background: '#5b8cff' }}
                  />
                </>
              )}
              <span className="source-node-field">{f.field_name}</span>
              <span className="source-node-type">{f.data_type}</span>
            </div>
          ))}
      </div>
    </div>
  )
}
