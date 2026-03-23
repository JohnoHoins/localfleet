import { useRef } from 'react'
import useWebSocket from './hooks/useWebSocket'
import FleetMap from './components/FleetMap'
import AssetCard from './components/AssetCard'
import CommandPanel from './components/CommandPanel'
import GpsDeniedToggle from './components/GpsDeniedToggle'
import MissionLog from './components/MissionLog'

const MAX_TRAIL = 200

export default function App() {
  const { fleetState, connected } = useWebSocket()
  const assets = fleetState?.assets || []
  const trails = useRef({})

  // Accumulate position history for trail lines
  for (const a of assets) {
    if (!trails.current[a.asset_id]) trails.current[a.asset_id] = []
    const t = trails.current[a.asset_id]
    const last = t[t.length - 1]
    // Only push if moved at least 2m (avoid piling up points when idle)
    if (!last || Math.abs(a.x - last[0]) > 2 || Math.abs(a.y - last[1]) > 2) {
      t.push([a.x, a.y])
      if (t.length > MAX_TRAIL) t.shift()
    }
  }

  return (
    <div className="h-screen flex flex-col" style={{ background: '#0b0f19' }}>
      {/* Header */}
      <header className="flex items-center justify-between px-4 py-2 border-b border-slate-800 shrink-0">
        <div className="flex items-center gap-3">
          <span className="text-blue-400 font-bold text-lg tracking-widest">LOCALFLEET</span>
          <span className="text-[10px] text-slate-600">C2 DASHBOARD</span>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className={`w-2 h-2 rounded-full ${connected ? 'bg-green-500' : 'bg-red-500'}`} />
          <span className="text-slate-500">{connected ? 'CONNECTED' : 'DISCONNECTED'}</span>
          {fleetState && (
            <span className="text-slate-600 ml-2">{assets.length} ASSETS</span>
          )}
        </div>
      </header>

      {/* Main content */}
      <div className="flex flex-1 min-h-0">
        {/* Map — 70% */}
        <div className="flex-[7] min-h-0">
          <FleetMap assets={assets} trails={trails.current} />
        </div>

        {/* Sidebar — 30% */}
        <div className="flex-[3] border-l border-slate-800 p-3 flex flex-col gap-3 overflow-y-auto">
          {/* Asset cards */}
          <div className="space-y-2">
            {assets.map((a) => (
              <AssetCard key={a.asset_id} asset={a} />
            ))}
          </div>

          <CommandPanel />
          <GpsDeniedToggle currentMode={fleetState?.gps_mode || 'full'} />
          <MissionLog fleetState={fleetState} />
        </div>
      </div>
    </div>
  )
}
