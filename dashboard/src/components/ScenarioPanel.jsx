import { useState } from 'react'

export default function ScenarioPanel() {
  const [running, setRunning] = useState(null)

  async function runScenario(name, steps) {
    setRunning(name)
    try {
      for (const step of steps) {
        await step()
      }
    } catch { /* swallow */ }
    setTimeout(() => setRunning(null), 1000)
  }

  const intercept = () =>
    runScenario('intercept', [
      () =>
        fetch('/api/contacts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            contact_id: 'bogey-1',
            x: 2000,
            y: 1000,
            heading: Math.PI, // west
            speed: 3.0,
            domain: 'surface',
          }),
        }),
      () =>
        fetch('/api/command', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            text: 'All assets intercept contact at 2000 1000 in echelon',
            source: 'text',
          }),
        }),
    ])

  const patrol = () =>
    runScenario('patrol', [
      () =>
        fetch('/api/command', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            text: 'All vessels patrol to 1500 800 in column',
            source: 'text',
          }),
        }),
    ])

  return (
    <div className="border border-slate-700 rounded p-3 bg-slate-900/50">
      <div className="text-xs text-slate-500 mb-2 font-bold tracking-wider">SCENARIOS</div>
      <div className="flex gap-2">
        <button
          onClick={intercept}
          disabled={running !== null}
          className="flex-1 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-600 rounded text-xs font-bold tracking-wider disabled:opacity-50"
        >
          {running === 'intercept' ? 'RUNNING...' : 'INTERCEPT'}
        </button>
        <button
          onClick={patrol}
          disabled={running !== null}
          className="flex-1 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-600 rounded text-xs font-bold tracking-wider disabled:opacity-50"
        >
          {running === 'patrol' ? 'RUNNING...' : 'PATROL'}
        </button>
      </div>
    </div>
  )
}
