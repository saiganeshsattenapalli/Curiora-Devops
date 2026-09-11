import { useState, Fragment } from 'react'
import ChatWindow from './ChatWindow'

const SAMPLE = `Traceback (most recent call last):
  File "app.py", line 3, in <module>
    import stripe
ModuleNotFoundError: No module named 'stripe'`

export default function ChatPanel({ busy, onRun }) {
  const [repository, setRepository] = useState('')
  const [source, setSource] = useState('railway')
  const [logs, setLogs] = useState('')

  function submit(event) {
    event.preventDefault()
    if (!logs.trim()) return
    onRun(event.nativeEvent.submitter?.value || 'analyze', { repository: repository.trim(), source, logs })
  }
  
  return <Fragment>
    <section id="incident" className="panel input-panel">
      <div className="panel-heading"><div><span className="eyebrow">01 / INCIDENT INPUT</span><h2>What went wrong?</h2></div><span className="terminal-icon">&gt;_</span></div>
      <form onSubmit={submit}>
        <fieldset disabled={!!busy}>
          <label htmlFor="repository">Repository</label>
          <div className="input-icon"><span aria-hidden="true">⑂</span><input id="repository" required value={repository} onChange={e => setRepository(e.target.value)} placeholder="owner/repository" pattern="[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]+" title="Enter a GitHub repository as owner/repository" autoComplete="off" spellCheck="false" /></div>
          <div className="field-row"><div><label htmlFor="source">Deployment source</label><select id="source" value={source} onChange={e => setSource(e.target.value)}><option value="railway">Railway</option><option value="vercel">Vercel</option></select></div><div><label htmlFor="branch">Target branch <span className="label-note">LOCKED</span></label><div className="locked-field"><span aria-hidden="true">⑂</span><input id="branch" value="dev" readOnly aria-readonly="true" /><span aria-label="locked">▣</span></div></div></div>
          <div className="log-label">
            <label htmlFor="logs">Incident logs <span className="label-note">/ MESSAGE</span></label>
            <button type="button" className="text-button" onClick={() => setLogs(SAMPLE)}>Load sample ↗</button>
          </div>
          <div className="log-editor"><div className="editor-top"><span className="editor-dots">● ● ●</span><span>deployment.log</span><span>TEXT</span></div><textarea id="logs" value={logs} onChange={e => setLogs(e.target.value)} required placeholder={'Paste your error logs here…\n\nTracebacks, build failures, deployment errors.\nGive CURIO the evidence to work with.'} spellCheck="false" /><div className="editor-bottom"><span>Logs are sent to your configured backend</span><span>{logs.length.toLocaleString()} chars</span></div></div>
          <div className="action-row"><button className="button secondary" name="action" value="analyze" type="submit" disabled={!logs.trim()}>{busy === 'analyze' ? 'Analyzing…' : '⌕  Analyze'}</button><button className="button primary" name="action" value="autofix" type="submit" disabled={!logs.trim()}>{busy === 'autofix' ? 'Working…' : '✧  Autofix'}<span>↗</span></button></div>
          <p className="form-note">Analyze returns a diagnosis. Autofix can push a fix branch and open a PR to <strong>dev</strong> after all checks pass.</p>
        </fieldset>
      </form>
    </section>
    <ChatWindow incidentContext={logs} setLogs={setLogs} />
  </Fragment>
}
