import { Handle, Position } from 'reactflow'
import './SourceGroupNode.css'

// Renders one landed source as a self-contained structure card: header +
// every observed field with its derived data_type. This is what shows up
// on the canvas automatically for each source -- clicking the header is
// what triggers relation discovery against every other loaded source.
export default function SourceGroupNode({ data }) {
  const { sourceSystem, fields, active, onActivate } = data

  return (
    <div className={`source-node ${active ? 'active' : ''}`}>
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <button className="source-node-header" onClick={onActivate}>
        <span className="source-node-name">{sourceSystem}</span>
        <span className="source-node-count">{fields ? fields.length : '…'} fields</span>
      </button>
      <div className="source-node-fields">
        {fields === null && <div className="source-node-loading">Loading structure…</div>}
        {fields && fields.length === 0 && <div className="source-node-loading">No fields detected</div>}
        {fields &&
          fields.map((f) => (
            <div key={f.field_name} className="source-node-row">
              <span className="source-node-field">{f.field_name}</span>
              <span className="source-node-type">{f.data_type}</span>
            </div>
          ))}
      </div>
    </div>
  )
}
