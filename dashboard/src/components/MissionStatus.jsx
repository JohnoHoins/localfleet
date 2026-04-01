const GPS_COLORS = { full: '#22c55e', degraded: '#f59e0b', denied: '#ef4444' }

const MISSION_COLORS = {
  patrol: '#22c55e',     // green
  search: '#3b82f6',     // blue
  escort: '#06b6d4',     // cyan
  loiter: '#f59e0b',     // amber
  aerial_recon: '#a855f7', // purple
  intercept: '#ef4444',  // red
}

const KILL_CHAIN_COLORS = {
  DETECT: '#eab308',   // yellow
  TRACK: '#f59e0b',    // amber
  LOCK: '#f97316',     // orange
  ENGAGE: '#ef4444',   // red
  CONVERGE: '#dc2626', // deep red
}

export default function MissionStatus({ fleetState, contacts = [] }) {
  if (!fleetState) return null

  const assets = fleetState.assets || []
  const gpsMode = fleetState.gps_mode || 'full'
  const mission = fleetState.active_mission
  const formation = fleetState.formation
  const threats = fleetState.threat_assessments || []
  const interceptRecommended = fleetState.intercept_recommended || false
  const recommendedTarget = fleetState.recommended_target || null
  const autonomy = fleetState.autonomy || {}
  const killChainPhase = autonomy.kill_chain_phase || null
  const killChainTarget = autonomy.kill_chain_target || null
  const targeting = autonomy.targeting || null
  const commsMode = autonomy.comms_mode || 'full'
  const commsDeniedDuration = autonomy.comms_denied_duration || 0
  const autonomousActions = autonomy.autonomous_actions || []

  // Asset status counts
  const counts = {}
  for (const a of assets) {
    counts[a.status] = (counts[a.status] || 0) + 1
  }
  const statusStr = Object.entries(counts)
    .map(([k, v]) => `${v} ${k.toUpperCase()}`)
    .join(' / ')

  // Fleet-to-contact bearing & distance
  let targetInfo = null
  if (contacts.length > 0 && assets.length > 0) {
    const avgX = assets.reduce((s, a) => s + a.x, 0) / assets.length
    const avgY = assets.reduce((s, a) => s + a.y, 0) / assets.length
    const c = contacts[0]
    const dx = c.x - avgX
    const dy = c.y - avgY
    const dist = Math.sqrt(dx * dx + dy * dy)
    // Nautical bearing: atan2(dx, dy) gives 0=North, CW+
    const bearing = ((Math.atan2(dx, dy) * 180 / Math.PI) % 360 + 360) % 360
    targetInfo = {
      id: c.contact_id,
      dist: dist >= 1000 ? `${(dist / 1000).toFixed(1)}km` : `${dist.toFixed(0)}m`,
      bearing: bearing.toFixed(0).padStart(3, '0'),
    }
  }

  return (
    <div className="border border-slate-700 rounded p-3 bg-slate-900/50">
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold tracking-wider" style={{ color: mission ? (MISSION_COLORS[mission] || '#cbd5e1') : '#cbd5e1' }}>
            {mission ? mission.toUpperCase() : 'STANDBY'}
          </span>
          {formation && (
            <span className="text-[10px] text-slate-500">/ {formation.toUpperCase()}</span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: GPS_COLORS[gpsMode] }} />
          <span className="text-[10px] text-slate-500">GPS {gpsMode.toUpperCase()}</span>
        </div>
      </div>

      <div className="text-[10px] text-slate-500">
        {statusStr}
        {contacts.length > 0 && (
          <span className="text-red-400 ml-2">{contacts.length} CONTACT{contacts.length > 1 ? 'S' : ''} TRACKED</span>
        )}
      </div>

      {targetInfo && (
        <div className="mt-1 text-xs text-red-400 font-bold">
          TARGET: {targetInfo.id.toUpperCase()} — {targetInfo.dist} @ {targetInfo.bearing}°
        </div>
      )}

      {/* Threat alerts */}
      {threats.filter(t => t.threat_level === 'warning' || t.threat_level === 'critical').map((t) => (
        <div key={t.contact_id} className={`mt-1 text-xs font-bold ${t.threat_level === 'critical' ? 'text-red-400' : 'text-orange-400'}`}>
          THREAT: {t.contact_id.toUpperCase()} — {(t.distance / 1000).toFixed(1)}km @ {t.bearing_deg.toFixed(0)}° CLOSING {Math.abs(t.closing_rate).toFixed(1)} m/s
        </div>
      ))}

      {interceptRecommended && (
        <div className="mt-1.5 text-xs font-bold text-red-400 animate-pulse">
          INTERCEPT RECOMMENDED — {recommendedTarget?.toUpperCase()}
        </div>
      )}

      {killChainPhase && (
        <div className="mt-1.5 border border-slate-700 rounded p-2 bg-slate-900/50">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: KILL_CHAIN_COLORS[killChainPhase] || '#6b7280' }} />
            <span className="text-xs font-bold tracking-wider" style={{ color: KILL_CHAIN_COLORS[killChainPhase] || '#6b7280' }}>
              KILL CHAIN: {killChainPhase}
            </span>
            {killChainTarget && (
              <span className="text-[10px] text-slate-500">/ {killChainTarget.toUpperCase()}</span>
            )}
          </div>
          {targeting && (
            <div className="text-[10px] text-slate-400 mt-0.5">
              BRG: {targeting.bearing_deg?.toFixed(0)}° RNG: {(targeting.range_m / 1000).toFixed(1)}km CONF: {(targeting.confidence * 100).toFixed(0)}%
              {targeting.locked && <span className="text-yellow-400 ml-1 font-bold">LOCKED</span>}
            </div>
          )}
        </div>
      )}

      {commsMode === 'denied' && (
        <div className="mt-2 border border-red-700 rounded p-2 bg-red-950/50">
          <div className="text-xs font-bold text-red-400 animate-pulse">
            COMMS DENIED — AUTONOMOUS
          </div>
          <div className="text-[10px] text-red-300 mt-0.5">
            Duration: {Math.floor(commsDeniedDuration)}s | Standing orders: {autonomy.comms_lost_behavior || 'return_to_base'}
          </div>
          {autonomousActions.length > 0 && (
            <div className="mt-1 space-y-0.5">
              {autonomousActions.map((action, i) => (
                <div key={i} className="text-[10px] text-orange-300 font-mono">
                  {action}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
