const STEPS = ['Detecting', 'Diagnosing', 'Patching', 'Validating', 'Reviewing', 'Creating PR']

function states(result, mode) {
  if (!result) return []
  const diagnosis = mode === 'analyze' ? result : result.diagnosis
  return [result.status === 'rejected_branch' ? 'failed' : 'done',
    diagnosis ? 'done' : 'failed',
    result.patch ? result.patch.success ? 'done' : 'failed' : 'idle',
    result.tests ? result.tests.passed && result.tests.return_code === 0 ? 'done' : 'failed' : 'idle',
    result.review ? result.review.approved ? 'done' : 'failed' : 'idle',
    result.pull_request ? 'done' : result.status === 'finalization_failed' ? 'failed' : 'idle']
}

export default function Pipeline({ busy, result, mode, error }) {
  const completed = states(result, mode)
  return <section className="pipeline" aria-label="Remediation pipeline">
    <div className="pipeline-steps">{STEPS.map((step, index) => {
      const pending = busy === 'autofix' || (busy === 'analyze' && index < 2)
      const state = pending ? 'pending' : completed[index] || 'idle'
      return <div key={step} className={`pipeline-step ${state}`}><span className="step-number" style={{ '--delay': `${index * 180}ms` }}>{state === 'done' ? '✓' : state === 'failed' ? '!' : String(index + 1).padStart(2, '0')}</span><span>{step}</span>{index < 5 && <span className="step-connector" />}</div>
    })}</div>
    <div className="pipeline-caption">{busy ? 'Request running · stages shown are the workflow, not live progress' : error ? 'Response unavailable · stage outcomes are unknown' : result ? `Backend status: ${result.status.replaceAll('_', ' ')} · stage outcomes reflect returned data` : 'One workflow. Every safety gate matters.'}</div>
  </section>
}
