import { useState } from 'react'
import CatalogView from './views/CatalogView'
import ExploreView from './views/ExploreView'
import ResolveView from './views/ResolveView'
import './App.css'

const TABS = [
  { id: 'explore', label: 'Explore' },
  { id: 'resolve', label: 'Resolve' },
  { id: 'catalog', label: 'Catalog' },
]

function App() {
  const [tab, setTab] = useState('explore')
  // Bump this to force child views to refetch after a curation decision
  // moves a candidate into the Catalog (closes the Explore -> Catalog loop).
  const [catalogVersion, setCatalogVersion] = useState(0)

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">SYNAPSE</div>
        <nav className="tabs">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={`tab ${tab === t.id ? 'active' : ''}`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>
      <main className="content">
        {tab === 'explore' && <ExploreView onCommitted={() => setCatalogVersion((v) => v + 1)} />}
        {tab === 'resolve' && <ResolveView />}
        {tab === 'catalog' && <CatalogView refreshKey={catalogVersion} />}
      </main>
    </div>
  )
}

export default App
