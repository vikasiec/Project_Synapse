import { Handle, NodeResizer, Position } from 'reactflow'
import './SourceGroupNode.css'

// Renders one landed source as a self-contained structure card: header +
// every observed field with its derived data_type. This is what shows up
// on the canvas automatically for each source. Single-click the header to
// trigger relation discovery against every other loaded source;
// double-click the card (or its "Properties" button) for the full field
// detail (entropy, regex matches, sample count). Resizable via the
// corner/edge handles so a source with many fields can be stretched
// taller instead of scrolling a tiny fixed box.
export default function SourceGroupNode({ id, data, selected }) {
  const { sourceSystem, fields, active, onActivate, onOpenProperties, fieldHandles } = data

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
        <button className="source-node-header-btn" onClick={onActivate} title="Find relations to every other loaded source">
          <span className="source-node-name">{sourceSystem}</span>
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
