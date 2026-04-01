import { useState } from 'react'

const MODES = ['full', 'degraded', 'denied']
const MODE_COLORS = { full: '#22c55e', degraded: '#f59e0b', denied: '#ef4444' }
const MODE_BG = { full: 'bg-slate-600', degraded: 'bg-amber-600', denied: 'bg-red-600' }
const MODE_TEXT = { full: 'text-green-400', degraded: 'text-amber-400', denied: 'text-red-400' }

export default function GpsDeniedToggle({ currentMode, assets = [] }) {
  const [loading, setLoading] = useState(false)

  const nextMode = MODES[(MODES.indexOf(currentMode) + 1) % MODES.length]

  async function cycle() {
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

  // Get max DR drift from surface assets when denied
  const maxDrift = currentMode === 'denied'
    ? Math.max(0, ...assets.filter(a => a.domain === 'surface').map(a => a.position_accuracy || 0))
    : 0

  return (
    <div className="border border-slate-700 rounded p-3 bg-slate-900/50 flex items-center justify-between">
      <div>
        <div className="text-xs text-slate-500 font-bold tracking-wider">GPS MODE</div>
        <div className={`text-sm font-bold ${MODE_TEXT[currentMode]}`}>
          {currentMode.toUpperCase()}
        </div>
        {currentMode === 'denied' && maxDrift > 0 && (
          <div className="text-[10px] text-red-400">DR DRIFT: {maxDrift.toFixed(0)}m</div>
        )}
      </div>
      <button
        onClick={cycle}
        disabled={loading}
        className={`px-3 py-1.5 rounded text-xs font-bold text-white transition-colors ${MODE_BG[currentMode]} hover:opacity-80 disabled:opacity-50`}
      >
        → {nextMode.toUpperCase()}
      </button>
    </div>
  )
}
