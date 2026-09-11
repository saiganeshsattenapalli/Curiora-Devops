const text = value => typeof value === 'string' ? value : '—'
function Badge({ good, children }) { return <span className={`badge ${good ? 'good' : 'warn'}`}>{children}</span> }
function Log({ title, children }) { return children ? <details className="log-details"><summary>{title}</summary><pre>{text(children)}</pre></details> : null }
function prLink(value) {
  try { const url = new URL(value); return url.protocol === 'https:' && url.hostname === 'github.com' && /^\/[^/]+\/[^/]+\/pull\/\d+\/?$/.test(url.pathname) ? url.href : null } catch { return null }
}
export default function IncidentResult({ result, diagnosis, mode }) {
  const { patch, tests, review, pull_request: pr } = result
  const confidence = typeof diagnosis?.confidence === 'number' ? Math.round(diagnosis.confidence * 100) : null
  const link = prLink(pr?.pr_url)
  return <div className="result-content">
    <div className="result-status"><Badge good={result.status === 'completed' || result.status === 'diagnosed'}>{result.status.replaceAll('_', ' ')}</Badge><span className="incident-id" title={result.incident_id}>#{result.incident_id.slice(0, 8)}</span></div>
    {result.error && <div role="alert" className="error-box">{text(result.error)}</div>}
    {result.cleanup_error && <div role="alert" className="error-box">{text(result.cleanup_error)}</div>}
    {diagnosis && <>
      <div className="diagnosis-title"><h3>{text(diagnosis.error_type).replaceAll('_', ' ')}</h3><span className="confidence">{confidence ?? '—'}<small>% confidence</small></span></div>
      <div className="confidence-track"><div style={{ width: `${Math.max(0, Math.min(100, confidence || 0))}%` }} /></div>
      <div className="result-block"><h4>ROOT CAUSE</h4><p>{text(diagnosis.root_cause)}</p></div>
      <div className="fix-card"><h4>↗ PROPOSED FIX</h4><p>{text(diagnosis.proposed_fix)}</p><Badge good={diagnosis.safe_to_autofix}>{diagnosis.safe_to_autofix ? 'Eligible for safety checks' : 'Manual investigation required'}</Badge></div>
      {diagnosis.affected_files?.length > 0 && <div className="result-block"><h4>DIAGNOSIS · AFFECTED FILES</h4><div className="file-list">{diagnosis.affected_files.map(file => <code key={file}>{text(file)}</code>)}</div></div>}
    </>}
    {mode === 'autofix' && <div className="stage-results">
      <section><div className="result-row"><h4>PATCH</h4>{patch ? <Badge good={patch.success}>{patch.success ? 'Applied' : 'Failed'}</Badge> : <span className="muted">Not reached</span>}</div>{patch && <><p>{text(patch.reason)}</p><div className="file-list">{patch.changed_files.map(file => <code key={file}>{text(file)}</code>)}</div><Log title="View unified diff">{patch.diff}</Log></>}</section>
      <section><div className="result-row"><h4>VALIDATION</h4>{tests ? <Badge good={tests.passed && tests.return_code === 0}>{tests.passed && tests.return_code === 0 ? 'Passed' : 'Failed'}</Badge> : <span className="muted">Not reached</span>}</div>{tests && <><p>{text(tests.reason)}</p><code className="command">{tests.command.join(' ')}</code><div className="test-meta">Exit code: {tests.return_code ?? '—'} <span>{tests.duration_ms} ms</span></div><Log title="Standard output">{tests.stdout}</Log><Log title="Standard error">{tests.stderr}</Log></>}</section>
      <section><div className="result-row"><h4>REVIEW</h4>{review ? <Badge good={review.approved}>{review.approved ? 'Approved' : 'Rejected'} · {text(review.risk)} risk</Badge> : <span className="muted">Not reached</span>}</div>{review && <><p>{text(review.summary)}</p>{review.issues?.length > 0 && <ul>{review.issues.map((issue, i) => <li key={i}>{text(issue)}</li>)}</ul>}</>}</section>
      <section><div className="result-row"><h4>PULL REQUEST</h4>{pr ? <Badge good>Created · {text(pr.base_branch)}</Badge> : <span className="muted">Not created</span>}</div>{pr && <div className="pr-card"><strong>{text(pr.pr_title)}</strong>{link ? <a href={link} target="_blank" rel="noopener noreferrer">Open PR #{pr.pr_number} <span>↗</span></a> : <p>PR #{pr.pr_number} · URL unavailable</p>}<code>{text(pr.pushed_branch)}</code><small>Commit: {text(pr.commit_sha)}</small></div>}</section>
    </div>}
    {(result.commit_sha || result.pushed_branch) && <div className="error-box"><strong>Partial finalization</strong><p>Check GitHub before retrying.</p><code>{text(result.pushed_branch)}</code><p>Commit: {text(result.commit_sha)}</p></div>}
  </div>
}
