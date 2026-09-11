import { useState, useRef } from 'react'
import { API_BASE } from '../api'

export default function ChatWindow({ incidentContext, setLogs }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [convId, setConvId] = useState(null)
  
  const [imagePreview, setImagePreview] = useState(null)
  const [imageFile, setImageFile] = useState(null)
  const fileInputRef = useRef(null)

  function handleFileChange(e) {
    const file = e.target.files?.[0]
    if (file) {
      setImageFile(file)
      setImagePreview(URL.createObjectURL(file))
    }
  }

  async function sendMessage(e) {
    e.preventDefault()
    if ((!input.trim() && !imageFile) || loading) return
    
    const userMsg = input.trim()
    setInput('')
    
    if (imageFile) {
      await sendVision(userMsg)
      return
    }
    
    setMessages(prev => [...prev, { role: 'user', content: userMsg }])
    setLoading(true)
    
    try {
      const payload = { message: userMsg }
      if (convId) payload.conversation_id = convId
      
      const res = await fetch(`${API_BASE}/api/v1/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      if (!res.ok) throw new Error('Chat failed')
      const data = await res.json()
      if (data.conversation_id) setConvId(data.conversation_id)
      setMessages(prev => [...prev, { role: 'assistant', content: data.message }])
    } catch (err) {
      setMessages(prev => [...prev, { role: 'assistant', content: 'Error: ' + err.message }])
    } finally {
      setLoading(false)
    }
  }

  async function sendVision(userMsg) {
    const previewUrl = imagePreview
    setMessages(prev => [...prev, { role: 'user', content: userMsg || 'Analyze this screenshot.', image: previewUrl }])
    setLoading(true)
    
    const formData = new FormData()
    formData.append('file', imageFile)
    if (userMsg) formData.append('message', userMsg)
    
    setImageFile(null)
    setImagePreview(null)
    
    try {
      const res = await fetch(`${API_BASE}/api/v1/incidents/vision`, {
        method: 'POST',
        body: formData
      })
      if (!res.ok) throw new Error('Vision extraction failed')
      const data = await res.json()
      
      setMessages(prev => [...prev, { 
        role: 'assistant', 
        content: `**Summary:**\n${data.summary}\n\n**Action:** ${data.suggested_action}`,
        extracted_logs: data.extracted_logs,
        isVision: true
      }])
    } catch (err) {
       setMessages(prev => [...prev, { role: 'assistant', content: 'Vision Error: ' + err.message }])
    } finally {
      setLoading(false)
    }
  }

  function handleUseLogs(extracted) {
    setLogs(prev => prev ? prev + '\n\n' + extracted : extracted)
  }

  return <section className="panel" style={{ marginTop: '22px', display: 'flex', flexDirection: 'column', height: '450px' }}>
    <div className="panel-heading"><div><span className="eyebrow">03 / ASSISTANT</span><h2>CURIO Chat</h2></div></div>
    
    <div style={{ flex: 1, padding: '16px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '10px' }}>
      {messages.length === 0 && <p style={{ color: '#8caaa0', fontSize: '11px', textAlign: 'center', margin: 'auto' }}>Ask a DevOps question or upload a screenshot...</p>}
      
      {messages.map((m, i) => (
        <div key={i} style={{ 
          alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
          background: m.role === 'user' ? 'var(--mint)' : '#1a2b25',
          color: m.role === 'user' ? '#123526' : '#bbccbf',
          padding: '10px 14px', borderRadius: '8px', maxWidth: '85%', fontSize: '11px', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere'
        }}>
          {m.image && <img src={m.image} alt="upload" style={{ maxWidth: '100%', borderRadius: '4px', marginBottom: '8px' }} />}
          <div>{m.content}</div>
          {m.isVision && m.extracted_logs && (
            <div style={{ marginTop: '10px' }}>
              <details style={{ background: '#0b1210', padding: '8px', borderRadius: '4px', marginBottom: '8px' }}>
                <summary style={{ cursor: 'pointer', color: '#9aefcc' }}>View Extracted Logs</summary>
                <pre style={{ marginTop: '8px', whiteSpace: 'pre-wrap', color: '#a2c8ac' }}>{m.extracted_logs}</pre>
              </details>
              <button type="button" className="button secondary" onClick={() => handleUseLogs(m.extracted_logs)} style={{ padding: '6px 12px', fontSize: '10px' }}>
                Use as incident logs
              </button>
            </div>
          )}
        </div>
      ))}
      
      {loading && <div style={{ alignSelf: 'flex-start', color: '#8caaa0', fontSize: '11px' }}>Thinking...</div>}
    </div>
    
    {imagePreview && (
      <div style={{ padding: '8px 16px', background: '#111819', borderTop: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: '10px' }}>
        <img src={imagePreview} alt="Preview" style={{ height: '40px', borderRadius: '4px' }} />
        <button type="button" onClick={() => { setImageFile(null); setImagePreview(null) }} style={{ background: 'none', border: 'none', color: '#ff6b6b', cursor: 'pointer', fontSize: '16px' }}>×</button>
      </div>
    )}
    
    <form onSubmit={sendMessage} style={{ display: 'flex', padding: '16px', borderTop: '1px solid var(--border)', gap: '10px', alignItems: 'center' }}>
      <input type="file" accept="image/*" onChange={handleFileChange} ref={fileInputRef} style={{ display: 'none' }} />
      <button type="button" onClick={() => fileInputRef.current?.click()} style={{ background: 'none', border: '1px solid #304137', color: '#8caaa0', borderRadius: '4px', padding: '8px 12px', cursor: 'pointer' }} title="Attach screenshot">
        📷
      </button>
      <input 
        value={input} 
        onChange={e => setInput(e.target.value)} 
        placeholder={imageFile ? "Add a message (optional)..." : "Ask CURIO..."} 
        style={{ flex: 1 }} 
      />
      <button type="submit" className="button primary" disabled={loading || (!input.trim() && !imageFile)}>Send</button>
    </form>
  </section>
}
