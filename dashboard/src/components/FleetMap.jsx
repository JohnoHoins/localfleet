import { MapContainer, TileLayer, Marker, Popup, Circle, useMap } from 'react-leaflet'
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

function FitBounds({ assets }) {
  const map = useMap()
  useEffect(() => {
    if (!assets?.length) return
    const bounds = assets.map((a) => metersToLatLng(a.x, a.y))
    map.fitBounds(bounds, { padding: [80, 80], maxZoom: 18 })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps -- fit once on mount
  return null
}

export default function FleetMap({ assets }) {
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
      {assets.map((asset) => {
        const pos = metersToLatLng(asset.x, asset.y)
        return (
          <span key={asset.asset_id}>
            {asset.gps_mode === 'degraded' && (
              <Circle
                center={pos}
                radius={asset.position_accuracy}
                pathOptions={{ color: '#f59e0b', fillColor: '#f59e0b', fillOpacity: 0.15, weight: 1 }}
                className="gps-uncertainty-ring"
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
    </MapContainer>
  )
}
