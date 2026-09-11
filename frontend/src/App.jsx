import { useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import CurioCore from './components/CurioCore'
import ChatPanel from './components/ChatPanel'
import Pipeline from './components/Pipeline'
import IncidentResult from './components/IncidentResult'
import { API_BASE, submitIncident } from './api'

export default function App() {
  const [busy, setBusy] = useState(null)
  const [result, setResult] = useState(null)
  const [mode, setMode] = useState(null)
  const [error, setError] = useState('')
  const inFlight = useRef(false)
  async function run(action, incident) {
    if (inFlight.current) return
    inFlight.current = true
    setBusy(action); setMode(action); setResult(null); setError('')
    try { setResult(await submitIncident(action, incident)) }
    catch (failure) { setError(failure.message) }
    finally { inFlight.current = false; setBusy(null) }
  }
  const diagnosis = mode === 'analyze' ? result : result?.diagnosis
  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="#top" aria-label="CURIO home"><span className="brand-symbol">C<span /></span>CURIO<span className="brand-dot">®</span></a>
      <div className="workspace-label">WORKSPACE <span>01</span></div>
      <nav aria-label="Sections">
        <a className="nav-link selected" href="#top"><span>⌘</span> Command center <i /></a>
        <a className="nav-link" href="#incident"><span>⌁</span> Incident input</a>
        <a className="nav-link" href="#results"><span>▤</span> Run results</a>
      </nav>
      <div className="sidebar-bottom"><div className="guard-icon">◇</div><strong>Built to act safely.</strong><p>Isolated fixes. Validated changes. Human-mergeable PRs.</p><div className="guard-row"><span className="dot" /> dev branch only</div><div className="sidebar-footer">CURIORA / DEVOPS <span>v0.1</span></div></div>
    </aside>
    <div className="main-shell" id="top">
      <header className="topbar"><div>Workspace <span>/</span> <strong>Command center</strong></div><span className="local-badge"><span className="dot" /> LOCAL DEMO</span></header>
      <main>
        <section className="hero">
          <div><div className="eyebrow"><span className="tiny-line" /> AUTONOMOUS DEVOPS COMMAND CENTER</div><h1>From failure<br />to <em>forward.</em></h1><p>Your logs. One intelligent workflow.<br />Diagnose, validate, and turn incidents into pull requests.</p><div className="hero-tags"><span>GPT-OSS reasoning</span><span>Deterministic safety gates</span></div></div>
          <div className="core-panel"><CurioCore active={!!busy} /><div className="core-caption"><span className={`dot ${busy ? 'pulse' : ''}`} /> CURIO CORE <span>{busy ? 'PROCESSING' : 'AWAITING INCIDENT'}</span></div></div>
        </section>
        <div className="section-heading"><h2>Remediation workspace</h2><span><span className="dot" /> {busy ? 'Request in progress' : result ? 'Response received' : 'Ready for an incident'}</span></div>
        <Pipeline busy={busy} result={result} mode={mode} error={error} />
        <div className="dashboard-grid">
          <ChatPanel busy={busy} onRun={run} />
          <section id="results" className="panel results-panel" aria-busy={!!busy}>
            <div className="panel-heading"><div><span className="eyebrow">02 / INTELLIGENCE</span><h2>Run results</h2></div><span className="subtle-badge">{mode === 'autofix' ? 'AUTOFIX' : mode === 'analyze' ? 'ANALYSIS' : 'LIVE OUTPUT'}</span></div>
            <div role="status" className="sr-only">{busy ? 'Waiting for the backend response.' : result ? `Run finished: ${result.status}` : ''}</div>
            <AnimatePresence mode="wait">
              {error ? <motion.div key="error" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="error-box" role="alert"><strong>Request could not complete</strong><p>{error}</p></motion.div>
              : result ? <motion.div key={result.incident_id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}><IncidentResult result={result} diagnosis={diagnosis} mode={mode} /></motion.div>
              : <motion.div key="empty" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="empty-state"><div className={`empty-icon ${busy ? 'pulse' : ''}`}>⌘</div><h3>{busy ? 'CURIO is on it.' : 'Your next fix starts here.'}</h3><p>{busy ? 'The backend is processing your incident. Results will appear when the request completes.' : 'Paste deployment logs and analyze an incident, or let CURIO prepare a validated fix.'}</p><div className="empty-terminal"><span>$ curio {busy || 'await-incident'}</span><br /><span className="muted">{busy ? '  waiting for backend response' : '  no incident submitted yet'}</span><span className="cursor" /></div></motion.div>}
            </AnimatePresence>
          </section>
        </div>
        <footer className="page-footer"><span>CURIO prepares the fix. You stay in control.</span><span title={API_BASE}>API · {API_BASE}</span></footer>
      </main>
    </div>
  </div>
}
