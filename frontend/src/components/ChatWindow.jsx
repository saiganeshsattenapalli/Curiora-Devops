import { useState } from 'react'
import { API_BASE } from '../api'

export default function ChatWindow({ incidentContext }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)

  async function sendMessage(e) {
    e.preventDefault()
    if (!input.trim() || loading) return
    const userMsg = input.trim()
    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: userMsg }])
    setLoading(true)

    try {
      const res = await fetch(`${API_BASE}/api/v1/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userMsg, incident_context: incidentContext })
      })
      if (!res.ok) throw new Error('Chat failed')
      const data = await res.json()
      setMessages(prev => [...prev, { role: 'assistant', content: data.response }])
    } catch (err) {
      setMessages(prev => [...prev, { role: 'assistant', content: 'Error: ' + err.message }])
    } finally {
      setLoading(false)
    }
  }

  return <section className="panel" style={{ marginTop: '22px', display: 'flex', flexDirection: 'column', height: '400px' }}>
    <div className="panel-heading"><div><span className="eyebrow">03 / ASSISTANT</span><h2>Ask GPT-OSS</h2></div></div>
    <div style={{ flex: 1, padding: '16px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '10px' }}>
      {messages.length === 0 && <p style={{ color: '#8caaa0', fontSize: '11px', textAlign: 'center', margin: 'auto' }}>Ask a question to the assistant...</p>}
      {messages.map((m, i) => (
        <div key={i} style={{ 
          alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
          background: m.role === 'user' ? 'var(--mint)' : '#1a2b25',
          color: m.role === 'user' ? '#123526' : '#bbccbf',
          padding: '8px 12px', borderRadius: '8px', maxWidth: '85%', fontSize: '11px', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere'
        }}>
          {m.content}
        </div>
      ))}
      {loading && <div style={{ alignSelf: 'flex-start', color: '#8caaa0', fontSize: '11px' }}>Thinking...</div>}
    </div>
    <form onSubmit={sendMessage} style={{ display: 'flex', padding: '16px', borderTop: '1px solid var(--border)' }}>
      <input 
        value={input} 
        onChange={e => setInput(e.target.value)} 
        placeholder="Type a message..." 
        style={{ flex: 1, marginRight: '10px' }} 
      />
      <button type="submit" className="button primary" disabled={loading || !input.trim()}>Send</button>
    </form>
  </section>
}
