import { useRef, useState } from 'react'
import { apiRequest } from '../lib/api'

export default function RTBButton({ commsDenied = false }) {
  const [loading, setLoading] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [error, setError] = useState(null)
  const resetTimer = useRef(null)

  async function handleRTB() {
    clearTimeout(resetTimer.current)
    setLoading(true)
    setConfirmed(false)
    setError(null)
    // Only an accepted recall is confirmed; a refusal (e.g. comms denied) is shown as such
    const r = await apiRequest('/api/return-to-base')
    setLoading(false)
    if (r.ok) {
      setConfirmed(true)
      resetTimer.current = setTimeout(() => setConfirmed(false), 2000)
    } else {
      setError(r.error)
      resetTimer.current = setTimeout(() => setError(null), 5000)
    }
  }

  let label = 'RETURN TO BASE'
  if (loading) label = 'RECALLING...'
  else if (confirmed) label = 'RTB CONFIRMED'
  else if (error) label = 'RTB REFUSED'
  else if (commsDenied) label = 'RTB UNAVAILABLE — COMMS DENIED'

  return (
    <div>
      <button
        onClick={handleRTB}
        disabled={loading || commsDenied}
        title={commsDenied ? 'Comms denied — fleet operating autonomously' : undefined}
        className={`w-full py-2 rounded font-bold text-sm tracking-wider transition-colors ${
          confirmed
            ? 'bg-green-700 text-green-200'
            : 'bg-red-900/60 hover:bg-red-800 text-red-300 border border-red-700/50'
        } disabled:opacity-50 disabled:cursor-not-allowed`}
      >
        {label}
      </button>
      {error && <div className="mt-1 text-[10px] text-red-400">ERROR: {error}</div>}
    </div>
  )
}
