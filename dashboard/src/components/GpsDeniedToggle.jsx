import { useState } from 'react'

export default function GpsDeniedToggle({ currentMode }) {
  const [loading, setLoading] = useState(false)
  const isDegraded = currentMode === 'degraded'

  async function toggle() {
    setLoading(true)
    try {
      await fetch('/api/gps-mode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mode: isDegraded ? 'full' : 'degraded',
          noise_meters: 25.0,
          update_rate_hz: 1.0,
        }),
      })
    } catch { /* swallow */ }
    setLoading(false)
  }

  return (
    <div className="border border-slate-700 rounded p-3 bg-slate-900/50 flex items-center justify-between">
      <div>
        <div className="text-xs text-slate-500 font-bold tracking-wider">GPS MODE</div>
        <div className={`text-sm font-bold ${isDegraded ? 'text-amber-400' : 'text-green-400'}`}>
          {isDegraded ? 'DEGRADED' : 'FULL'}
        </div>
      </div>
      <button
        onClick={toggle}
        disabled={loading}
        className={`relative w-12 h-6 rounded-full transition-colors ${isDegraded ? 'bg-amber-600' : 'bg-slate-600'}`}
      >
        <span
          className={`absolute top-0.5 w-5 h-5 bg-white rounded-full transition-transform ${isDegraded ? 'translate-x-6' : 'translate-x-0.5'}`}
        />
      </button>
    </div>
  )
}
