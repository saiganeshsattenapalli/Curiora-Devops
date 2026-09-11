export const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/+$/, '')

export async function submitIncident(mode, incident) {
  let response
  try {
    response = await fetch(`${API_BASE}/api/v1/incidents${mode === 'autofix' ? '/autofix' : ''}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...incident, branch: 'dev' }),
    })
  } catch {
    throw new Error(`Cannot reach ${API_BASE}. Check the backend and CORS configuration. ${mode === 'autofix' ? 'If the request reached the server, remediation may still be running. Check GitHub before retrying.' : ''}`)
  }
  let data
  try { data = await response.json() } catch {
    throw new Error(`The backend returned a non-JSON response (HTTP ${response.status}). Check server logs before retrying.`)
  }
  if (!response.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : Array.isArray(data.detail)
      ? data.detail.map(item => `${item.loc?.join('.')}: ${item.msg}`).join('; ') : 'Request failed'
    throw new Error(`HTTP ${response.status}: ${detail}`)
  }
  if (!data || typeof data.status !== 'string' || typeof data.incident_id !== 'string' ||
      (mode === 'analyze' && typeof data.root_cause !== 'string')) {
    throw new Error('The backend returned an unexpected response. Check server logs before retrying.')
  }
  return data
}
