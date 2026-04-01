import { useState } from 'react'

export default function RTBButton() {
  const [loading, setLoading] = useState(false)
  const [confirmed, setConfirmed] = useState(false)

  async function handleRTB() {
    setLoading(true)
    setConfirmed(false)
    try {
      const res = await fetch('/api/return-to-base', { method: 'POST' })
      if (res.ok) {
        setConfirmed(true)
        setTimeout(() => setConfirmed(false), 2000)
      }
    } catch { /* swallow */ }
    setLoading(false)
  }

  return (
    <button
      onClick={handleRTB}
      disabled={loading}
      className={`w-full py-2 rounded font-bold text-sm tracking-wider transition-colors ${
        confirmed
          ? 'bg-green-700 text-green-200'
          : 'bg-red-900/60 hover:bg-red-800 text-red-300 border border-red-700/50'
      } disabled:opacity-50`}
    >
      {loading ? 'RECALLING...' : confirmed ? 'RTB CONFIRMED' : 'RETURN TO BASE'}
    </button>
  )
}
