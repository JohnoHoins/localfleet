import { useRef, useState, useCallback } from 'react'
import useWebSocket from './hooks/useWebSocket'
import FleetMap from './components/FleetMap'
import AssetCard from './components/AssetCard'
import CommandPanel from './components/CommandPanel'
import GpsDeniedToggle from './components/GpsDeniedToggle'
import MissionLog from './components/MissionLog'
import MissionStatus from './components/MissionStatus'
import RTBButton from './components/RTBButton'
import ContactPanel from './components/ContactPanel'
import ScenarioPanel from './components/ScenarioPanel'

const MAX_TRAIL = 200

export default function App() {
  const { fleetState, connected } = useWebSocket()
  const assets = fleetState?.assets || []
  const contacts = fleetState?.contacts || []
  const trails = useRef({})
  const contactTrails = useRef({})
  const commsMode = fleetState?.autonomy?.comms_mode || 'full'

  const toggleCommsMode = useCallback(async () => {
    const newMode = commsMode === 'full' ? 'denied' : 'full'
    try {
      await fetch('/api/comms-mode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: newMode }),
      })
    } catch (e) {
      console.error('Failed to toggle comms mode:', e)
    }
  }, [commsMode])

  // Accumulate position history for asset trail lines
  for (const a of assets) {
    if (!trails.current[a.asset_id]) trails.current[a.asset_id] = []
    const t = trails.current[a.asset_id]
    const last = t[t.length - 1]
    if (!last || Math.abs(a.x - last[0]) > 2 || Math.abs(a.y - last[1]) > 2) {
      t.push([a.x, a.y])
      if (t.length > MAX_TRAIL) t.shift()
    }
  }

  // Accumulate position history for contact trail lines
  for (const c of contacts) {
    if (!contactTrails.current[c.contact_id]) contactTrails.current[c.contact_id] = []
    const t = contactTrails.current[c.contact_id]
    const last = t[t.length - 1]
    if (!last || Math.abs(c.x - last[0]) > 2 || Math.abs(c.y - last[1]) > 2) {
      t.push([c.x, c.y])
      if (t.length > MAX_TRAIL) t.shift()
    }
  }

  // Clean up trails for contacts that no longer exist
  const activeContactIds = new Set(contacts.map(c => c.contact_id))
  for (const id of Object.keys(contactTrails.current)) {
    if (!activeContactIds.has(id)) delete contactTrails.current[id]
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
          <FleetMap
            assets={assets}
            trails={trails.current}
            contacts={contacts}
            contactTrails={contactTrails.current}
            activeMission={fleetState?.active_mission || null}
            threatAssessments={fleetState?.threat_assessments || []}
            autonomy={fleetState?.autonomy || {}}
          />
        </div>

        {/* Sidebar — 30% */}
        <div className="flex-[3] border-l border-slate-800 p-3 flex flex-col gap-3 overflow-y-auto">
          <MissionStatus fleetState={fleetState} contacts={contacts} />

          {/* Asset cards */}
          <div className="space-y-2">
            {assets.map((a) => (
              <AssetCard key={a.asset_id} asset={a} />
            ))}
          </div>

          <ContactPanel
            contacts={contacts}
            interceptRecommended={fleetState?.intercept_recommended || false}
            recommendedTarget={fleetState?.recommended_target || null}
            threatAssessments={fleetState?.threat_assessments || []}
          />
          <CommandPanel />

          <div className="flex gap-2">
            <div className="flex-1">
              <RTBButton />
            </div>
          </div>

          <GpsDeniedToggle currentMode={fleetState?.gps_mode || 'full'} assets={assets} />

          {/* Comms Mode Toggle */}
          <div className="border border-slate-700 rounded p-2 bg-slate-900/50">
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-400">COMMS LINK</span>
              <button
                onClick={toggleCommsMode}
                className={`px-3 py-1 text-xs font-bold rounded transition-colors ${
                  commsMode === 'denied'
                    ? 'bg-red-700 text-white animate-pulse'
                    : 'bg-green-700 text-white'
                }`}
              >
                {commsMode === 'denied' ? 'DENIED' : 'FULL'}
              </button>
            </div>
          </div>
          <ScenarioPanel />
          <MissionLog fleetState={fleetState} />
        </div>
      </div>
    </div>
  )
}
