import { MapContainer, TileLayer, Marker, Popup, Circle, Polyline, Polygon, useMap } from 'react-leaflet'
import L from 'leaflet'
import { useEffect, useMemo } from 'react'

// Convert meters (local frame) to lat/lng. Origin ~42°N.
const ORIGIN_LAT = 42.0
const ORIGIN_LNG = -70.0
const M_PER_DEG_LAT = 111320
const M_PER_DEG_LNG = 82000 // ~at 42° latitude

function metersToLatLng(x, y) {
  return [ORIGIN_LAT + y / M_PER_DEG_LAT, ORIGIN_LNG + x / M_PER_DEG_LNG]
}

function createIcon(domain, heading, label) {
  const isSurface = domain === 'surface'
  const color = isSurface ? '#3b82f6' : '#06b6d4'
  const shape = isSurface
    ? `<polygon points="16,2 4,30 16,24 28,30" fill="${color}" stroke="#fff" stroke-width="0.5" opacity="0.9"/>`
    : `<polygon points="16,2 2,16 16,10 30,16" fill="${color}" stroke="#fff" stroke-width="0.5" opacity="0.9"/>
       <polygon points="16,22 2,16 16,30 30,16" fill="${color}" stroke="#fff" stroke-width="0.5" opacity="0.5"/>`

  const html = `<div style="display:flex;flex-direction:column;align-items:center">
    <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32"
      style="transform:rotate(${heading}deg);filter:drop-shadow(0 0 3px ${color})">
      ${shape}
    </svg>
    <span style="font-size:9px;color:${color};font-weight:bold;text-shadow:0 0 4px #000,0 0 4px #000;white-space:nowrap;margin-top:2px">${label}</span>
  </div>`

  return L.divIcon({
    html,
    className: '',
    iconSize: [32, 48],
    iconAnchor: [16, 16],
  })
}

const THREAT_COLORS = {
  none: '#6b7280',      // gray
  detected: '#eab308',  // yellow
  warning: '#f97316',   // orange
  critical: '#ef4444',  // red
}

function createContactIcon(heading, label, threatLevel) {
  const color = THREAT_COLORS[threatLevel] || '#ef4444'
  const pulse = threatLevel === 'critical' ? 'animation:pulse 1s infinite;' : ''
  const shape = `<polygon points="16,2 4,28 28,28" fill="${color}" stroke="#fff" stroke-width="0.5" opacity="0.9"/>`

  const html = `<div style="display:flex;flex-direction:column;align-items:center;${pulse}">
    <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32"
      style="transform:rotate(${heading}deg);filter:drop-shadow(0 0 3px ${color})">
      ${shape}
    </svg>
    <span style="font-size:9px;color:${color};font-weight:bold;text-shadow:0 0 4px #000,0 0 4px #000;white-space:nowrap;margin-top:2px">${label}</span>
  </div>`

  return L.divIcon({
    html,
    className: '',
    iconSize: [32, 48],
    iconAnchor: [16, 16],
  })
}

// Cape Cod coastline polygon (lat, lng) from land_check.py
const CAPE_COD_LATLNG = [
  [41.74, -70.62], [41.67, -70.52], [41.63, -70.30], [41.65, -70.00],
  [41.67, -69.95], [41.70, -69.94], [41.80, -69.96], [41.88, -69.97],
  [41.93, -69.97], [42.00, -70.03], [42.04, -70.08], [42.06, -70.17],
  [42.07, -70.21], [42.05, -70.25], [42.03, -70.19], [41.98, -70.10],
  [41.92, -70.07], [41.85, -70.05], [41.77, -70.06], [41.73, -70.10],
  [41.73, -70.20], [41.73, -70.40], [41.76, -70.55], [41.77, -70.62],
]

function FitBounds({ assets }) {
  const map = useMap()
  useEffect(() => {
    if (!assets?.length) return
    const bounds = assets.map((a) => metersToLatLng(a.x, a.y))
    map.fitBounds(bounds, { padding: [80, 80], maxZoom: 18 })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps -- fit once on mount
  return null
}

const TRAIL_COLORS = {
  surface: '#3b82f680',
  air: '#06b6d480',
}

function computeInterceptPoint(fleetX, fleetY, fleetSpeed, tX, tY, tHdg, tSpd) {
  if (fleetSpeed <= 0) return null
  let predX = tX, predY = tY
  for (let i = 0; i < 3; i++) {
    const dist = Math.sqrt((predX - fleetX) ** 2 + (predY - fleetY) ** 2)
    if (dist < 1) break
    const t = dist / fleetSpeed
    predX = tX + tSpd * Math.cos(tHdg) * t
    predY = tY + tSpd * Math.sin(tHdg) * t
  }
  return [predX, predY]
}

function createInterceptIcon() {
  const html = `<div style="display:flex;align-items:center;justify-content:center">
    <svg width="20" height="20" viewBox="0 0 20 20">
      <circle cx="10" cy="10" r="8" fill="none" stroke="#f59e0b" stroke-width="2" stroke-dasharray="3 2"/>
      <line x1="10" y1="2" x2="10" y2="18" stroke="#f59e0b" stroke-width="1.5"/>
      <line x1="2" y1="10" x2="18" y2="10" stroke="#f59e0b" stroke-width="1.5"/>
    </svg>
  </div>`
  return L.divIcon({ html, className: '', iconSize: [20, 20], iconAnchor: [10, 10] })
}

export default function FleetMap({ assets, trails = {}, contacts = [], contactTrails = {}, activeMission = null, threatAssessments = [], autonomy = {} }) {
  const center = useMemo(() => {
    if (!assets?.length) return [ORIGIN_LAT, ORIGIN_LNG]
    const avgX = assets.reduce((s, a) => s + a.x, 0) / assets.length
    const avgY = assets.reduce((s, a) => s + a.y, 0) / assets.length
    return metersToLatLng(avgX, avgY)
  }, [assets])

  if (!assets) return null

  return (
    <MapContainer center={center} zoom={14} className="h-full w-full" zoomControl={false}>
      <TileLayer
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution=""
        className="dark-map-tiles"
      />
      <FitBounds assets={assets} />

      {/* Coastline overlay */}
      <Polygon
        positions={CAPE_COD_LATLNG}
        pathOptions={{ color: '#92400e', fillColor: '#92400e', fillOpacity: 0.15, weight: 1.5 }}
      />

      {/* Threat detection range rings — only when contacts exist */}
      {contacts.length > 0 && assets.length > 0 && (() => {
        const surfaceAssets = assets.filter(a => a.domain === 'surface')
        const src = surfaceAssets.length > 0 ? surfaceAssets : assets
        const cX = src.reduce((s, a) => s + a.x, 0) / src.length
        const cY = src.reduce((s, a) => s + a.y, 0) / src.length
        const centroid = metersToLatLng(cX, cY)
        return (
          <>
            <Circle center={centroid} radius={8000}
              pathOptions={{ color: '#eab308', fillOpacity: 0, weight: 0.5, dashArray: '8 4', opacity: 0.3 }} />
            <Circle center={centroid} radius={5000}
              pathOptions={{ color: '#f97316', fillOpacity: 0, weight: 0.8, dashArray: '6 3', opacity: 0.4 }} />
            <Circle center={centroid} radius={2000}
              pathOptions={{ color: '#ef4444', fillOpacity: 0, weight: 1, dashArray: '4 2', opacity: 0.5 }} />
          </>
        )
      })()}

      {/* Asset trail lines */}
      {assets.map((asset) => {
        const trail = trails[asset.asset_id]
        if (!trail || trail.length < 2) return null
        const positions = trail.map(([x, y]) => metersToLatLng(x, y))
        return (
          <Polyline
            key={`trail-${asset.asset_id}`}
            positions={positions}
            pathOptions={{
              color: TRAIL_COLORS[asset.domain] || '#3b82f680',
              weight: 2,
              dashArray: asset.domain === 'air' ? '6 4' : undefined,
            }}
          />
        )
      })}

      {/* Contact trail lines */}
      {contacts.map((contact) => {
        const trail = contactTrails[contact.contact_id]
        if (!trail || trail.length < 2) return null
        const positions = trail.map(([x, y]) => metersToLatLng(x, y))
        return (
          <Polyline
            key={`ctrail-${contact.contact_id}`}
            positions={positions}
            pathOptions={{ color: '#ef444480', weight: 2, dashArray: '4 4' }}
          />
        )
      })}

      {/* Fleet-to-contact line + intercept geometry */}
      {contacts.length > 0 && assets.length > 0 && (() => {
        const surfaceAssets = assets.filter(a => a.domain === 'surface')
        const avgX = surfaceAssets.length > 0
          ? surfaceAssets.reduce((s, a) => s + a.x, 0) / surfaceAssets.length
          : assets.reduce((s, a) => s + a.x, 0) / assets.length
        const avgY = surfaceAssets.length > 0
          ? surfaceAssets.reduce((s, a) => s + a.y, 0) / surfaceAssets.length
          : assets.reduce((s, a) => s + a.y, 0) / assets.length
        const c = contacts[0]
        const intercept = (activeMission === 'intercept' && c.speed > 0)
          ? computeInterceptPoint(avgX, avgY, 8.0, c.x, c.y, c.heading, c.speed)
          : null
        return (
          <>
            <Polyline
              positions={[metersToLatLng(avgX, avgY), metersToLatLng(c.x, c.y)]}
              pathOptions={{ color: '#ef444440', weight: 1, dashArray: '2 6' }}
            />
            {intercept && (
              <>
                <Polyline
                  positions={[metersToLatLng(c.x, c.y), metersToLatLng(intercept[0], intercept[1])]}
                  pathOptions={{ color: '#f59e0b80', weight: 1.5, dashArray: '4 4' }}
                />
                <Polyline
                  positions={[metersToLatLng(avgX, avgY), metersToLatLng(intercept[0], intercept[1])]}
                  pathOptions={{ color: '#f59e0b60', weight: 1, dashArray: '6 4' }}
                />
                <Marker position={metersToLatLng(intercept[0], intercept[1])} icon={createInterceptIcon()} />
              </>
            )}
          </>
        )
      })()}

      {/* Drone targeting line — yellow line when locked */}
      {autonomy?.targeting?.locked && (() => {
        const drone = assets.find(a => a.domain === 'air')
        const targetContact = contacts.find(c => c.contact_id === autonomy.targeting.contact_id)
        if (!drone || !targetContact) return null
        return (
          <Polyline
            positions={[metersToLatLng(drone.x, drone.y), metersToLatLng(targetContact.x, targetContact.y)]}
            pathOptions={{ color: '#eab308', weight: 2, dashArray: '6 3' }}
          />
        )
      })()}

      {/* Asset markers */}
      {assets.map((asset) => {
        const pos = metersToLatLng(asset.x, asset.y)
        return (
          <span key={asset.asset_id}>
            {asset.gps_mode === 'denied' && (
              <Circle
                center={pos}
                radius={asset.position_accuracy}
                pathOptions={{ color: '#ef4444', fillColor: '#ef4444', fillOpacity: 0.08, weight: 1, dashArray: '4 3' }}
              />
            )}
            <Marker position={pos} icon={createIcon(asset.domain, asset.heading, asset.asset_id.toUpperCase())}>
              <Popup className="c2-popup">
                <div className="text-xs" style={{ color: '#0b0f19' }}>
                  <div className="font-bold text-sm">{asset.asset_id.toUpperCase()}</div>
                  <div>{asset.domain.toUpperCase()} — {asset.status}</div>
                  <div>SPD: {asset.speed.toFixed(1)} m/s HDG: {asset.heading.toFixed(0)}°</div>
                  {asset.domain === 'air' && <div>ALT: {asset.altitude?.toFixed(0) ?? '—'} m</div>}
                  {asset.risk_level > 0 && <div>RISK: {asset.risk_level.toFixed(2)}</div>}
                  {asset.cpa != null && <div>CPA: {asset.cpa.toFixed(0)}m TCPA: {asset.tcpa?.toFixed(0)}s</div>}
                  <div>GPS: {asset.gps_mode} (±{asset.position_accuracy.toFixed(0)}m)</div>
                </div>
              </Popup>
            </Marker>
          </span>
        )
      })}

      {/* Contact markers — color-coded by threat level */}
      {contacts.map((contact) => {
        const pos = metersToLatLng(contact.x, contact.y)
        const nautHdg = ((90 - contact.heading * 180 / Math.PI) % 360 + 360) % 360
        const ta = threatAssessments.find(t => t.contact_id === contact.contact_id)
        const threatLevel = ta?.threat_level || 'none'
        return (
          <Marker
            key={`contact-${contact.contact_id}`}
            position={pos}
            icon={createContactIcon(nautHdg, contact.contact_id.toUpperCase(), threatLevel)}
          >
            <Popup className="c2-popup">
              <div className="text-xs" style={{ color: '#0b0f19' }}>
                <div className="font-bold text-sm" style={{ color: THREAT_COLORS[threatLevel] || '#ef4444' }}>
                  {contact.contact_id.toUpperCase()} — {threatLevel.toUpperCase()}
                </div>
                <div>CONTACT — {contact.domain?.toUpperCase() || 'SURFACE'}</div>
                <div>SPD: {contact.speed.toFixed(1)} m/s HDG: {nautHdg.toFixed(0)}°</div>
                {ta && <div>RANGE: {(ta.distance / 1000).toFixed(1)}km BRG: {ta.bearing_deg.toFixed(0)}°</div>}
                {ta && <div>CLOSING: {ta.closing_rate.toFixed(1)} m/s</div>}
                {ta && <div>ACTION: {ta.recommended_action.toUpperCase()}</div>}
              </div>
            </Popup>
          </Marker>
        )
      })}
    </MapContainer>
  )
}
