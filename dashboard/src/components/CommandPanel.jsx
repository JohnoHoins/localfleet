import { useState } from 'react'
import VoiceButton from './VoiceButton'

export default function CommandPanel() {
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)
  const [result, setResult] = useState(null)
  const [history, setHistory] = useState([])
  const [showHistory, setShowHistory] = useState(false)

  async function handleSend() {
    if (!text.trim() || sending) return
    setSending(true)
    setResult(null)

    const t0 = performance.now()
    try {
      const res = await fetch('/api/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, source: 'text' }),
      })
      const data = await res.json()
      const elapsed = performance.now() - t0
      const resultData = { ...data, client_ms: elapsed.toFixed(0) }
      setResult(resultData)
      if (data.success) {
        const ms = data.llm_response_time_ms
        setHistory(prev => [
          { text: text.trim(), time: ms != null ? `${(ms / 1000).toFixed(1)}s` : '—' },
          ...prev,
        ].slice(0, 5))
        setText('')
      }
    } catch (err) {
      setResult({ success: false, error: err.message })
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="border border-slate-700 rounded p-3 bg-slate-900/50">
      <div className="text-xs text-slate-500 mb-2 font-bold tracking-wider">COMMAND</div>
      <div className="flex gap-2">
        <input
          className="flex-1 bg-slate-800 border border-slate-600 rounded px-2 py-1.5 text-sm text-slate-200 outline-none focus:border-blue-500"
          placeholder="Enter natural language command..."
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          disabled={sending}
        />
        <button
          className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded font-bold disabled:opacity-50"
          onClick={handleSend}
          disabled={sending || !text.trim()}
        >
          {sending ? '...' : 'SEND'}
        </button>
        <VoiceButton onResult={(data) => setResult({ ...data, client_ms: '—' })} />
      </div>

      {history.length > 0 && (
        <div className="mt-2">
          <button
            onClick={() => setShowHistory(h => !h)}
            className="text-[10px] text-slate-500 hover:text-slate-300 transition-colors"
          >
            {showHistory ? '\u25BC' : '\u25B6'} HISTORY ({history.length})
          </button>
          {showHistory && (
            <div className="mt-1 space-y-0.5">
              {history.map((h, i) => (
                <div key={i} className="flex items-center gap-2 text-[10px] text-slate-500">
                  <span className="truncate flex-1">&gt; "{h.text}"</span>
                  <span className="px-1 rounded font-bold bg-amber-900/50 text-amber-400">LLM</span>
                  <span className="text-slate-600 w-14 text-right">{h.time}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {result && (
        <div className={`mt-2 text-xs p-2 rounded ${result.success ? 'bg-green-900/30 text-green-400' : 'bg-red-900/30 text-red-400'}`}>
          {result.success ? (
            <>
              <div className="flex items-center gap-2">
                <span>OK</span>
                {result.fleet_command && result.llm_response_time_ms != null && (
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-800 text-amber-300">
                    LLM {(result.llm_response_time_ms / 1000).toFixed(1)}s
                  </span>
                )}
              </div>
              {result.fleet_command && (
                <pre className="mt-1 text-[10px] text-slate-400 overflow-x-auto max-h-24 overflow-y-auto">
                  {JSON.stringify(result.fleet_command, null, 2)}
                </pre>
              )}
            </>
          ) : (
            <div>ERROR: {result.error}</div>
          )}
        </div>
      )}
    </div>
  )
}
