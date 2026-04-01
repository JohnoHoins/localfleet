const GPS_COLORS = { full: '#22c55e', degraded: '#f59e0b', denied: '#ef4444' }

export default function MissionStatus({ fleetState, contacts = [] }) {
  if (!fleetState) return null

  const assets = fleetState.assets || []
  const gpsMode = fleetState.gps_mode || 'full'
  const mission = fleetState.active_mission
  const formation = fleetState.formation
  const threats = fleetState.threat_assessments || []
  const interceptRecommended = fleetState.intercept_recommended || false
  const recommendedTarget = fleetState.recommended_target || null

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
          <span className="text-xs font-bold tracking-wider text-slate-300">
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
    </div>
  )
}
