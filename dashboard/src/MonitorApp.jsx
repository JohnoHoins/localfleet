import { useState, useEffect, useRef } from 'react'

const KILL_CHAIN_PHASES = ['DETECT', 'TRACK', 'LOCK', 'ENGAGE']

function useMonitorWs() {
  const [data, setData] = useState(null)
  const [connected, setConnected] = useState(false)
  const wsRef = useRef(null)

  useEffect(() => {
    function connect() {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      const ws = new WebSocket(`${proto}://${location.host}/monitor/ws`)
      wsRef.current = ws
      ws.onopen = () => setConnected(true)
      ws.onclose = () => {
        setConnected(false)
        setTimeout(connect, 2000)
      }
      ws.onmessage = (e) => {
        try { setData(JSON.parse(e.data)) } catch {}
      }
    }
    connect()
    return () => wsRef.current?.close()
  }, [])

  return { data, connected }
}

function Flash({ value, children }) {
  const prev = useRef(value)
  const [flash, setFlash] = useState(false)
  useEffect(() => {
    if (value !== prev.current) {
      setFlash(true)
      prev.current = value
      const t = setTimeout(() => setFlash(false), 200)
      return () => clearTimeout(t)
    }
  }, [value])
  return <span className={flash ? 'monitor-flash' : ''}>{children}</span>
}

function CommandPanel({ command }) {
  if (!command?.last_text) {
    return (
      <div className="monitor-panel">
        <div className="panel-title">COMMAND PARSER</div>
        <div className="dim">Awaiting command...</div>
      </div>
    )
  }
  const timeStr = command.parse_time_ms != null
    ? `${(command.parse_time_ms / 1000).toFixed(1)}s`
    : '\u2014'

  return (
    <div className="monitor-panel">
      <div className="panel-title">COMMAND PARSER</div>
      <div className="cmd-text">&gt; "{command.last_text}"</div>
      <div className="row">
        <span className="label">Method:</span>
        <Flash value={command.parse_method}>
          <span style={{ color: command.parse_method === 'direct' ? '#06b6d4' : '#f59e0b', fontWeight: 'bold' }}>
            {command.parse_method === 'direct' ? 'DIRECT' : 'LLM'}
          </span>
        </Flash>
        {command.parse_method !== 'direct' && (
          <span className="dim" style={{ marginLeft: 8 }}>({timeStr})</span>
        )}
      </div>
      <div className="row">
        <span className="label">Mission:</span>
        <span className="value">{command.mission_type || '\u2014'}</span>
      </div>
      <div className="row">
        <span className="label">Formation:</span>
        <span className="value">{command.formation || '\u2014'}</span>
      </div>
    </div>
  )
}

function ThreatPanel({ threats }) {
  const activePhase = threats?.kill_chain_phase?.toUpperCase()
  return (
    <div className="monitor-panel">
      <div className="panel-title">THREAT ENGINE</div>
      <div className="row">
        <span className="label">Contacts:</span>
        <Flash value={threats?.contact_count}>
          <span className="value">{threats?.contact_count ?? 0}</span>
        </Flash>
      </div>
      {threats?.critical > 0 && (
        <div className="critical-pulse">
          CRITICAL: {threats.critical} contact{threats.critical > 1 ? 's' : ''}
        </div>
      )}
      {threats?.warning > 0 && (
        <div style={{ color: '#f97316' }}>
          WARNING: {threats.warning} contact{threats.warning > 1 ? 's' : ''}
        </div>
      )}
      <div className="row" style={{ marginTop: 8 }}>
        <span className="label">Kill Chain:</span>
      </div>
      <div className="kill-chain">
        {KILL_CHAIN_PHASES.map((phase, i) => (
          <span key={phase}>
            <span className={`kc-phase ${activePhase === phase ? 'kc-active' : ''}`}>
              {phase}
            </span>
            {i < KILL_CHAIN_PHASES.length - 1 && <span className="kc-arrow">{' \u2192 '}</span>}
          </span>
        ))}
      </div>
      {threats?.kill_chain_target && (
        <div className="dim" style={{ marginTop: 4 }}>
          Target: {threats.kill_chain_target}
        </div>
      )}
      {threats?.auto_engage_countdown != null && (
        <div style={{ marginTop: 8 }}>
          <div className="label">Auto-engage in:</div>
          <div className="countdown-bar">
            <div
              className="countdown-fill"
              style={{ width: `${Math.max(0, (threats.auto_engage_countdown / 60) * 100)}%` }}
            />
            <span className="countdown-text">{threats.auto_engage_countdown.toFixed(0)}s</span>
          </div>
        </div>
      )}
    </div>
  )
}

function SimPanel({ sim, comms, gps, performance }) {
  const commsColor = comms?.mode === 'denied' ? '#ef4444' : '#22c55e'
  const gpsColor = gps?.mode === 'denied' ? '#ef4444' : gps?.mode === 'degraded' ? '#f59e0b' : '#22c55e'
  return (
    <div className="monitor-panel">
      <div className="panel-title">SIMULATION ENGINE</div>
      <div className="row">
        <span className="label">Tick:</span>
        <Flash value={sim?.tick_count}>
          <span className="value">{sim?.tick_count ?? 0}</span>
        </Flash>
        <span style={{ marginLeft: 12 }} className="label">Speed:</span>
        <span className="value">{sim?.time_scale ?? 1}x</span>
      </div>
      <div className="row">
        <span className="label">Assets:</span>
        <span className="value">{sim?.assets_executing ?? 0} exec</span>
        <span className="dim"> / {sim?.assets_idle ?? 0} idle</span>
      </div>
      <div className="row">
        <span className="label">Comms:</span>
        <Flash value={comms?.mode}>
          <span style={{ color: commsColor, fontWeight: 'bold' }}>
            {comms?.mode?.toUpperCase() ?? 'FULL'}
          </span>
        </Flash>
        {comms?.mode === 'denied' && (
          <span className="dim"> ({comms.denied_duration}s)</span>
        )}
      </div>
      <div className="row">
        <span className="label">GPS:</span>
        <Flash value={gps?.mode}>
          <span style={{ color: gpsColor, fontWeight: 'bold' }}>
            {gps?.mode?.toUpperCase() ?? 'FULL'}
          </span>
        </Flash>
        {gps?.blending && <span style={{ color: '#f59e0b' }}> BLENDING</span>}
      </div>
      <div className="row">
        <span className="label">Standing:</span>
        <span className="value">{comms?.standing_orders ?? 'return_to_base'}</span>
      </div>
      <div className="row">
        <span className="label">Step:</span>
        <span className="value">{performance?.step_time_us ?? 0}\u00b5s</span>
      </div>
      <div className="row">
        <span className="label">Ollama:</span>
        <span style={{ color: performance?.ollama_loaded ? '#22c55e' : '#ef4444' }}>
          {performance?.ollama_loaded ? 'loaded' : 'offline'}
        </span>
        <span className="dim"> ({performance?.ollama_model ?? '?'})</span>
      </div>
      <div className="row">
        <span className="label">WS clients:</span>
        <span className="value">{performance?.ws_clients ?? 0}</span>
      </div>
    </div>
  )
}

function DecisionLog({ decisions }) {
  return (
    <div className="monitor-panel decision-panel">
      <div className="panel-title">DECISION LOG</div>
      <div className="decision-scroll">
        {(!decisions || decisions.length === 0) ? (
          <div className="dim">No decisions yet...</div>
        ) : (
          decisions.slice().reverse().map((d, i) => {
            const time = d.timestamp
              ? new Date(d.timestamp * 1000).toLocaleTimeString('en-US', { hour12: false })
              : '??:??:??'
            const typeColor = {
              threat_assessment: '#ef4444',
              auto_track: '#06b6d4',
              kill_chain: '#f59e0b',
              auto_engage: '#ef4444',
              intercept_solution: '#f59e0b',
              replan: '#8b5cf6',
              comms_denied: '#ef4444',
              gps_mode_change: '#f97316',
            }[d.type] || '#64748b'
            return (
              <div key={d.id || i} className="decision-entry">
                <div className="decision-header">
                  <span className="decision-time">{time}</span>
                  <span style={{ color: typeColor }}>[{d.type?.toUpperCase()}]</span>
                </div>
                <div className="decision-action">{d.action}</div>
                {d.confidence != null && (
                  <div className="dim">conf: {d.confidence.toFixed(2)}</div>
                )}
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}

export default function MonitorApp() {
  const { data, connected } = useMonitorWs()

  return (
    <div className="monitor-root">
      <style>{`
        .monitor-root {
          background: #0a0e17;
          color: #e2e8f0;
          font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', 'Consolas', monospace;
          font-size: 13px;
          height: 100vh;
          display: flex;
          flex-direction: column;
          overflow: hidden;
        }
        .monitor-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 8px 16px;
          border-bottom: 1px solid #1e293b;
          flex-shrink: 0;
        }
        .monitor-title {
          color: #06b6d4;
          font-weight: bold;
          font-size: 15px;
          letter-spacing: 3px;
        }
        .monitor-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          grid-template-rows: 1fr 1fr;
          gap: 1px;
          flex: 1;
          min-height: 0;
          background: #1e293b;
        }
        .monitor-panel {
          background: #0a0e17;
          padding: 12px 16px;
          overflow: hidden;
          display: flex;
          flex-direction: column;
        }
        .decision-panel {
          overflow: hidden;
        }
        .decision-scroll {
          flex: 1;
          overflow-y: auto;
          min-height: 0;
        }
        .panel-title {
          color: #06b6d4;
          font-size: 11px;
          font-weight: bold;
          letter-spacing: 2px;
          margin-bottom: 10px;
          padding-bottom: 4px;
          border-bottom: 1px solid #1e293b;
        }
        .row {
          margin-bottom: 3px;
        }
        .label {
          color: #64748b;
          margin-right: 6px;
        }
        .value {
          color: #e2e8f0;
        }
        .dim {
          color: #475569;
        }
        .cmd-text {
          color: #94a3b8;
          font-size: 12px;
          margin-bottom: 8px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .critical-pulse {
          color: #ef4444;
          font-weight: bold;
          animation: pulse 1s infinite;
        }
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
        .monitor-flash {
          animation: flash-bg 200ms ease-out;
        }
        @keyframes flash-bg {
          from { background: rgba(6, 182, 212, 0.3); }
          to { background: transparent; }
        }
        .kill-chain {
          display: flex;
          align-items: center;
          gap: 2px;
          font-size: 12px;
          margin-top: 2px;
        }
        .kc-phase {
          color: #475569;
          padding: 1px 4px;
          border-radius: 2px;
        }
        .kc-active {
          color: #f59e0b;
          font-weight: bold;
          background: rgba(245, 158, 11, 0.15);
        }
        .kc-arrow {
          color: #334155;
        }
        .countdown-bar {
          position: relative;
          height: 16px;
          background: #1e293b;
          border-radius: 3px;
          margin-top: 4px;
          overflow: hidden;
        }
        .countdown-fill {
          height: 100%;
          background: linear-gradient(90deg, #ef4444, #f59e0b);
          transition: width 0.5s linear;
          border-radius: 3px;
        }
        .countdown-text {
          position: absolute;
          top: 0;
          left: 0;
          right: 0;
          text-align: center;
          font-size: 10px;
          line-height: 16px;
          color: #fff;
          font-weight: bold;
        }
        .decision-entry {
          margin-bottom: 6px;
          padding-bottom: 4px;
          border-bottom: 1px solid #0f172a;
        }
        .decision-header {
          display: flex;
          gap: 8px;
          font-size: 11px;
        }
        .decision-time {
          color: #475569;
        }
        .decision-action {
          color: #94a3b8;
          font-size: 12px;
          margin-top: 1px;
        }
        .conn-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          display: inline-block;
          margin-right: 6px;
        }
        .decision-scroll::-webkit-scrollbar { width: 4px; }
        .decision-scroll::-webkit-scrollbar-track { background: transparent; }
        .decision-scroll::-webkit-scrollbar-thumb { background: #334155; border-radius: 2px; }
      `}</style>

      <div className="monitor-header">
        <span className="monitor-title">SYSTEM MONITOR</span>
        <div style={{ display: 'flex', alignItems: 'center', fontSize: 11 }}>
          <span className="conn-dot" style={{ background: connected ? '#22c55e' : '#ef4444' }} />
          <span style={{ color: '#64748b' }}>{connected ? 'CONNECTED' : 'DISCONNECTED'}</span>
        </div>
      </div>

      <div className="monitor-grid">
        <CommandPanel command={data?.command} />
        <ThreatPanel threats={data?.threats} />
        <SimPanel
          sim={data?.sim}
          comms={data?.comms}
          gps={data?.gps}
          performance={data?.performance}
        />
        <DecisionLog decisions={data?.decisions} />
      </div>
    </div>
  )
}
