import { useEffect, useRef, useState } from 'react'

export default function MissionLog({ fleetState }) {
  const [entries, setEntries] = useState([])
  const prevRef = useRef(null)
  const scrollRef = useRef(null)

  useEffect(() => {
    if (!fleetState) return
    const prev = prevRef.current
    const newEntries = []
    const ts = new Date(fleetState.timestamp * 1000).toLocaleTimeString('en-US', { hour12: false })

    if (prev) {
      // GPS mode change
      if (prev.gps_mode !== fleetState.gps_mode) {
        newEntries.push({ ts, msg: `GPS mode → ${fleetState.gps_mode.toUpperCase()}` })
      }
      // Mission change
      if (prev.active_mission !== fleetState.active_mission && fleetState.active_mission) {
        newEntries.push({ ts, msg: `Mission: ${fleetState.active_mission.toUpperCase()}` })
      }
      // Per-asset status changes
      const prevAssets = Object.fromEntries((prev.assets || []).map((a) => [a.asset_id, a]))
      for (const asset of fleetState.assets) {
        const pa = prevAssets[asset.asset_id]
        if (pa && pa.status !== asset.status) {
          newEntries.push({ ts, msg: `${asset.asset_id.toUpperCase()} → ${asset.status.toUpperCase()}` })
        }
      }
    } else {
      newEntries.push({ ts, msg: `Fleet online — ${fleetState.assets.length} assets` })
    }

    prevRef.current = fleetState
    if (newEntries.length > 0) {
      setEntries((e) => [...e.slice(-100), ...newEntries])
    }
  }, [fleetState])

  useEffect(() => {
    scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight)
  }, [entries])

  return (
    <div className="border border-slate-700 rounded p-3 bg-slate-900/50 flex flex-col min-h-0">
      <div className="text-xs text-slate-500 mb-2 font-bold tracking-wider">MISSION LOG</div>
      <div ref={scrollRef} className="flex-1 overflow-y-auto text-xs text-slate-400 space-y-0.5 max-h-40">
        {entries.length === 0 && <div className="text-slate-600">Waiting for events...</div>}
        {entries.map((e, i) => (
          <div key={i}>
            <span className="text-slate-600">{e.ts}</span> {e.msg}
          </div>
        ))}
      </div>
    </div>
  )
}
