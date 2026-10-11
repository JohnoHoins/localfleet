/**
 * Threat helpers shared by MissionStatus and FleetMap, so the status panel,
 * the map and the backend threat engine all talk about the same contact.
 */

/**
 * The contact the fleet is working: the kill-chain target, else the
 * recommended intercept target, else the closest assessed contact, else the
 * first contact. Returns { contact, assessment } or null.
 */
export function pickTarget(contacts = [], threatAssessments = [], autonomy = {}, recommendedTarget = null) {
  if (contacts.length === 0) return null
  const byId = (id) => (id ? contacts.find((c) => c.contact_id === id) : undefined)
  const closest = threatAssessments.reduce(
    (best, t) => (best == null || t.distance < best.distance ? t : best),
    null,
  )
  const contact = byId(autonomy?.kill_chain_target)
    || byId(recommendedTarget)
    || byId(closest?.contact_id)
    || contacts[0]
  const assessment = threatAssessments.find((t) => t.contact_id === contact.contact_id) || null
  return { contact, assessment }
}

/** Fleet centroid as the threat engine computes it: surface vessels only. */
export function surfaceCentroid(assets = []) {
  const surface = assets.filter((a) => a.domain === 'surface')
  const src = surface.length > 0 ? surface : assets
  if (src.length === 0) return null
  return {
    x: src.reduce((s, a) => s + a.x, 0) / src.length,
    y: src.reduce((s, a) => s + a.y, 0) / src.length,
  }
}

/** closing_rate is in m/s: negative = closing, positive = opening. */
export function closingTrend(rate) {
  if (Math.abs(rate) < 0.05) return 'STEADY'
  return rate < 0 ? 'CLOSING' : 'OPENING'
}
