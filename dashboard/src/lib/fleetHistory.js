/**
 * History built up from the /ws frame stream: position trails and the
 * MISSION LOG event lines. Pure functions, applied once per frame by
 * useWebSocket's reducer.
 */

const MAX_TRAIL = 200
const TRAIL_BREAK_M = 500 // a jump this large is a respawn/reset, not motion

/**
 * Extend each item's trail with its current position (after >2 m of motion).
 * Items no longer in the frame are dropped.
 */
export function appendTrails(trails, items, idKey) {
  const next = {}
  for (const item of items) {
    const id = item[idKey]
    const t = trails[id] || []
    const last = t[t.length - 1]
    if (last && Math.hypot(item.x - last[0], item.y - last[1]) > TRAIL_BREAK_M) {
      next[id] = [[item.x, item.y]]
    } else if (!last || Math.abs(item.x - last[0]) > 2 || Math.abs(item.y - last[1]) > 2) {
      next[id] = [...t.slice(-(MAX_TRAIL - 1)), [item.x, item.y]]
    } else {
      next[id] = t
    }
  }
  return next
}

/** MISSION LOG lines for what changed between two consecutive frames. */
export function diffFleetEvents(prev, fleetState) {
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
    for (const asset of fleetState.assets || []) {
      const pa = prevAssets[asset.asset_id]
      if (pa && pa.status !== asset.status) {
        newEntries.push({ ts, msg: `${asset.asset_id.toUpperCase()} → ${asset.status.toUpperCase()}` })
      }
    }
    // Threat level changes
    const prevThreats = Object.fromEntries((prev.threat_assessments || []).map((t) => [t.contact_id, t]))
    for (const ta of (fleetState.threat_assessments || [])) {
      const pt = prevThreats[ta.contact_id]
      if (pt && pt.threat_level !== ta.threat_level) {
        if (ta.threat_level === 'warning' || ta.threat_level === 'critical') {
          newEntries.push({ ts, msg: `THREAT: ${ta.contact_id.toUpperCase()} escalated to ${ta.threat_level.toUpperCase()}` })
        }
      } else if (!pt && (ta.threat_level === 'warning' || ta.threat_level === 'critical')) {
        newEntries.push({ ts, msg: `THREAT: ${ta.contact_id.toUpperCase()} ${ta.threat_level.toUpperCase()} at ${(ta.distance / 1000).toFixed(1)}km` })
      }
    }
    // Intercept recommendation
    if (!prev.intercept_recommended && fleetState.intercept_recommended && fleetState.recommended_target) {
      newEntries.push({ ts, msg: `AUTO: INTERCEPT recommended for ${fleetState.recommended_target.toUpperCase()}` })
    }
  } else {
    newEntries.push({ ts, msg: `Fleet online — ${(fleetState.assets || []).length} assets` })
  }

  return newEntries
}
