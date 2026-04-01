import { useState } from 'react'

export default function ContactPanel({ contacts = [], interceptRecommended = false, recommendedTarget = null, threatAssessments = [] }) {
  const [id, setId] = useState('bogey-1')
  const [x, setX] = useState('2000')
  const [y, setY] = useState('1000')
  const [hdg, setHdg] = useState('270')
  const [spd, setSpd] = useState('3.0')
  const [spawning, setSpawning] = useState(false)

  async function handleSpawn() {
    setSpawning(true)
    try {
      const hdgDeg = parseFloat(hdg)
      const mathRad = (90 - hdgDeg) * Math.PI / 180
      await fetch('/api/contacts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          contact_id: id,
          x: parseFloat(x),
          y: parseFloat(y),
          heading: mathRad,
          speed: parseFloat(spd),
          domain: 'surface',
        }),
      })
    } catch { /* swallow */ }
    setSpawning(false)
  }

  async function handleRemove(contactId) {
    try {
      await fetch(`/api/contacts/${contactId}`, { method: 'DELETE' })
    } catch { /* swallow */ }
  }

  async function handleIntercept() {
    if (!recommendedTarget) return
    const contact = contacts.find(c => c.contact_id === recommendedTarget)
    if (!contact) return
    try {
      await fetch('/api/command-direct', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mission_type: 'intercept',
          assets: [
            { asset_id: 'alpha', domain: 'surface', waypoints: [{ x: contact.x, y: contact.y }], speed: 8.0 },
            { asset_id: 'bravo', domain: 'surface', waypoints: [{ x: contact.x, y: contact.y }], speed: 8.0 },
            { asset_id: 'charlie', domain: 'surface', waypoints: [{ x: contact.x, y: contact.y }], speed: 8.0 },
            { asset_id: 'eagle-1', domain: 'air', waypoints: [{ x: contact.x, y: contact.y }], speed: 15.0, altitude: 100.0, drone_pattern: 'track' },
          ],
          formation: 'echelon',
        }),
      })
    } catch { /* swallow */ }
  }

  return (
    <div className="border border-slate-700 rounded p-3 bg-slate-900/50">
      <div className="text-xs text-slate-500 mb-2 font-bold tracking-wider">CONTACTS</div>

      <div className="grid grid-cols-2 gap-1.5 mb-2">
        <input
          className="col-span-2 bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200 outline-none focus:border-red-500"
          placeholder="contact_id"
          value={id}
          onChange={(e) => setId(e.target.value)}
        />
        <input
          className="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200 outline-none"
          placeholder="X (m)"
          value={x}
          onChange={(e) => setX(e.target.value)}
        />
        <input
          className="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200 outline-none"
          placeholder="Y (m)"
          value={y}
          onChange={(e) => setY(e.target.value)}
        />
        <input
          className="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200 outline-none"
          placeholder="HDG (°)"
          value={hdg}
          onChange={(e) => setHdg(e.target.value)}
        />
        <input
          className="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200 outline-none"
          placeholder="SPD (m/s)"
          value={spd}
          onChange={(e) => setSpd(e.target.value)}
        />
      </div>

      <button
        onClick={handleSpawn}
        disabled={spawning || !id.trim()}
        className="w-full py-1.5 bg-red-900/60 hover:bg-red-800 text-red-300 border border-red-700/50 rounded text-xs font-bold tracking-wider disabled:opacity-50"
      >
        {spawning ? 'SPAWNING...' : 'SPAWN CONTACT'}
      </button>

      {interceptRecommended && recommendedTarget && (
        <button
          onClick={handleIntercept}
          className="w-full mt-2 py-2 bg-red-700 hover:bg-red-600 text-white border border-red-500 rounded text-xs font-bold tracking-wider animate-pulse"
        >
          INTERCEPT {recommendedTarget.toUpperCase()}
        </button>
      )}

      {contacts.length > 0 && (
        <div className="mt-2 space-y-1">
          {contacts.map((c) => {
            const nautHdg = ((90 - c.heading * 180 / Math.PI) % 360 + 360) % 360
            return (
              <div key={c.contact_id} className="flex items-center justify-between text-xs text-red-300 bg-red-900/20 rounded px-2 py-1">
                <span>{c.contact_id.toUpperCase()} — {c.speed.toFixed(1)}m/s @ {nautHdg.toFixed(0)}°</span>
                <button
                  onClick={() => handleRemove(c.contact_id)}
                  className="text-red-500 hover:text-red-300 font-bold ml-2"
                >
                  ×
                </button>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
