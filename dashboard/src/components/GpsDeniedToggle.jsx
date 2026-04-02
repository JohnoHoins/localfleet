import { useState } from 'react'

export default function GpsDeniedToggle({ currentMode, assets = [] }) {
  const [loading, setLoading] = useState(false)
  const isDenied = currentMode === 'denied'
  const nextMode = isDenied ? 'full' : 'denied'

  async function toggle() {
    setLoading(true)
    try {
      await fetch('/api/gps-mode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mode: nextMode,
          noise_meters: 25.0,
          update_rate_hz: 1.0,
        }),
      })
    } catch { /* swallow */ }
    setLoading(false)
  }

  const maxDrift = isDenied
    ? Math.max(0, ...assets.filter(a => a.domain === 'surface').map(a => a.position_accuracy || 0))
    : 0

  return (
    <div className="border border-slate-700 rounded p-2 bg-slate-900/50">
      <div className="flex items-center justify-between">
        <div>
          <span className="text-xs text-slate-400">GPS</span>
          {isDenied && maxDrift > 0 && (
            <span className="text-[10px] text-red-400 ml-2">DR DRIFT: {maxDrift.toFixed(0)}m</span>
          )}
        </div>
        <button
          onClick={toggle}
          disabled={loading}
          className={`px-3 py-1 text-xs font-bold rounded transition-colors ${
            isDenied
              ? 'bg-red-700 text-white'
              : 'bg-green-700 text-white'
          } hover:opacity-80 disabled:opacity-50`}
        >
          {isDenied ? 'DENIED' : 'FULL'}
        </button>
      </div>
    </div>
  )
}
