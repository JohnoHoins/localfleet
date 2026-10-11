import { useState, useCallback, useEffect } from 'react'
import useWebSocket from './hooks/useWebSocket'
import { apiRequest } from './lib/api'
import FleetMap from './components/FleetMap'
import AssetCard from './components/AssetCard'
import CommandPanel from './components/CommandPanel'
import GpsDeniedToggle from './components/GpsDeniedToggle'
import MissionLog from './components/MissionLog'
import MissionStatus from './components/MissionStatus'
import RTBButton from './components/RTBButton'
import ContactPanel from './components/ContactPanel'
import ScenarioPanel from './components/ScenarioPanel'

const SIM_SPEEDS = [1, 2, 4, 8]

export default function App() {
  const { fleetState, trails, contactTrails, log, connected } = useWebSocket()
  const assets = fleetState?.assets || []
  const contacts = fleetState?.contacts || []
  const commsMode = fleetState?.autonomy?.comms_mode || 'full'
  const commsDenied = commsMode === 'denied'
  const [timeScale, setTimeScale] = useState(null) // null until the backend reports it
  const [controlError, setControlError] = useState(null)

  // SIM SPEED shows the backend's speed: read it on every (re)connect, so a
  // page reload or a backend restart never leaves a stale highlight.
  useEffect(() => {
    if (!connected) return
    let cancelled = false
    apiRequest('/api/time-scale', { method: 'GET' }).then((r) => {
      if (!cancelled && r.ok) setTimeScale(r.data.time_scale)
    })
    return () => { cancelled = true }
  }, [connected])
  const shownTimeScale = fleetState?.time_scale ?? timeScale

  const changeTimeScale = useCallback(async (scale) => {
    const r = await apiRequest('/api/time-scale', { json: { scale } })
    if (r.ok) {
      setTimeScale(r.data.time_scale ?? scale)
      setControlError(null)
    } else {
      setControlError(`SIM SPEED: ${r.error}`)
    }
  }, [])

  const toggleCommsMode = useCallback(async () => {
    const newMode = commsMode === 'full' ? 'denied' : 'full'
    const r = await apiRequest('/api/comms-mode', { json: { mode: newMode } })
    setControlError(r.ok ? null : `COMMS LINK: ${r.error}`)
  }, [commsMode])

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
            trails={trails}
            contacts={contacts}
            contactTrails={contactTrails}
            activeMission={fleetState?.active_mission || null}
            threatAssessments={fleetState?.threat_assessments || []}
            autonomy={fleetState?.autonomy || {}}
            recommendedTarget={fleetState?.recommended_target || null}
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
            commsDenied={commsDenied}
          />
          <CommandPanel commsDenied={commsDenied} />

          <div className="flex gap-2">
            <div className="flex-1">
              <RTBButton commsDenied={commsDenied} />
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
                  commsDenied
                    ? 'bg-red-700 text-white animate-pulse'
                    : 'bg-green-700 text-white'
                }`}
              >
                {commsDenied ? 'DENIED' : 'FULL'}
              </button>
            </div>
          </div>

          {/* Sim Speed Control */}
          <div className="border border-slate-700 rounded p-2 bg-slate-900/50">
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-400">SIM SPEED</span>
              <div className="flex gap-1">
                {SIM_SPEEDS.map((s) => (
                  <button
                    key={s}
                    onClick={() => changeTimeScale(s)}
                    className={`px-2 py-0.5 text-xs font-bold rounded transition-colors ${
                      shownTimeScale === s
                        ? 'bg-blue-600 text-white'
                        : 'bg-slate-700 text-slate-400 hover:bg-slate-600'
                    }`}
                  >
                    {s}x
                  </button>
                ))}
              </div>
            </div>
          </div>
          {controlError && (
            <div className="text-[10px] text-red-400">ERROR: {controlError}</div>
          )}
          <ScenarioPanel commsDenied={commsDenied} />
          <MissionLog fleetState={fleetState} log={log} />
        </div>
      </div>
    </div>
  )
}
