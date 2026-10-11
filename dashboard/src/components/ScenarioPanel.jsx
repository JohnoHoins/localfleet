import { useState } from 'react'
import { apiRequest, commandWarnings } from '../lib/api'

export default function ScenarioPanel({ commsDenied = false }) {
  const [running, setRunning] = useState(null)
  const [status, setStatus] = useState(null) // outcome of the last run

  // Runs the steps in order and stops at the first one the backend refuses
  async function runScenario(name, steps) {
    setRunning(name)
    setStatus(null)
    let outcome = { ok: true, text: `${name.toUpperCase()}: OK`, warnings: [] }
    for (const step of steps) {
      const r = await step()
      if (!r.ok) {
        outcome = { ok: false, text: `${name.toUpperCase()} FAILED: ${r.error}`, warnings: [] }
        break
      }
      outcome.warnings.push(...commandWarnings(r))
    }
    setStatus(outcome)
    setTimeout(() => setRunning(null), 1000)
  }

  const intercept = () =>
    runScenario('intercept', [
      () =>
        apiRequest('/api/contacts', {
          json: {
            contact_id: 'bogey-1',
            x: 2000,
            y: 1000,
            heading: Math.PI, // west
            speed: 3.0,
            domain: 'surface',
          },
        }),
      () =>
        apiRequest('/api/command', {
          json: {
            text: 'All assets intercept contact at 2000 1000 in echelon',
            source: 'text',
          },
        }),
    ])

  const patrol = () =>
    runScenario('patrol', [
      () =>
        apiRequest('/api/command', {
          json: {
            text: 'All vessels patrol to 1500 800 in column',
            source: 'text',
          },
        }),
    ])

  const disabled = running !== null || commsDenied
  const title = commsDenied ? 'Comms denied — fleet operating autonomously' : undefined

  return (
    <div className="border border-slate-700 rounded p-3 bg-slate-900/50">
      <div className="text-xs text-slate-500 mb-2 font-bold tracking-wider">SCENARIOS</div>
      <div className="flex gap-2">
        <button
          onClick={intercept}
          disabled={disabled}
          title={title}
          className="flex-1 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-600 rounded text-xs font-bold tracking-wider disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {running === 'intercept' ? 'RUNNING...' : 'INTERCEPT'}
        </button>
        <button
          onClick={patrol}
          disabled={disabled}
          title={title}
          className="flex-1 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-600 rounded text-xs font-bold tracking-wider disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {running === 'patrol' ? 'RUNNING...' : 'PATROL'}
        </button>
      </div>
      {status && (
        <div className={`mt-2 text-[10px] ${status.ok ? 'text-green-400' : 'text-red-400'}`}>
          {status.text}
          {status.warnings.map((w, i) => (
            <div key={i} className="text-amber-400">⚠ {w}</div>
          ))}
        </div>
      )}
    </div>
  )
}
