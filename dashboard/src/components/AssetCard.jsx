const STATUS_COLORS = {
  idle: '#6b7280',
  executing: '#22c55e',
  avoiding: '#eab308',
  returning: '#3b82f6',
  error: '#ef4444',
}

export default function AssetCard({ asset }) {
  const statusColor = STATUS_COLORS[asset.status] || '#6b7280'
  const isSurface = asset.domain === 'surface'

  return (
    <div className="border border-slate-700 rounded px-3 py-2 bg-slate-900/50">
      <div className="flex items-center justify-between mb-1">
        <span className="font-bold text-sm tracking-wide">{asset.asset_id.toUpperCase()}</span>
        <div className="flex items-center gap-2">
          {asset.gps_mode === 'degraded' && (
            <span className="text-[10px] px-1 rounded bg-amber-900 text-amber-300">GPS-DENIED</span>
          )}
          <span
            className="text-[10px] font-bold px-1.5 py-0.5 rounded"
            style={{ backgroundColor: isSurface ? '#1e3a5f' : '#164e63', color: isSurface ? '#60a5fa' : '#22d3ee' }}
          >
            {asset.domain.toUpperCase()}
          </span>
        </div>
      </div>

      <div className="flex items-center gap-2 text-xs text-slate-400 mb-1">
        <span className="inline-block w-2 h-2 rounded-full" style={{ backgroundColor: statusColor }} />
        <span>{asset.status.toUpperCase()}</span>
        {asset.mission_type && <span className="text-slate-500">/ {asset.mission_type}</span>}
      </div>

      <div className="grid grid-cols-2 gap-x-4 text-xs text-slate-400">
        <span>SPD {asset.speed.toFixed(1)} m/s</span>
        <span>HDG {asset.heading.toFixed(0)}°</span>
        {!isSurface && (
          <>
            <span>ALT {asset.altitude?.toFixed(0) ?? '—'} m</span>
            <span>PTN {asset.drone_pattern ?? '—'}</span>
          </>
        )}
        {isSurface && asset.risk_level > 0 && (
          <>
            <span>RISK {asset.risk_level.toFixed(2)}</span>
            <span>CPA {asset.cpa?.toFixed(0) ?? '—'}m</span>
          </>
        )}
      </div>
    </div>
  )
}
