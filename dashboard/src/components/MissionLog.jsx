import { useEffect, useRef, useState } from 'react'

const DECISION_COLORS = {
  intercept_solution: 'text-red-400',
  threat_assessment: 'text-orange-400',
  auto_track: 'text-yellow-400',
  kill_chain_transition: 'text-red-300',
  replan: 'text-blue-400',
  comms_fallback: 'text-amber-400',
  auto_engage: 'text-red-500',
  intercept_complete: 'text-green-400',
}

const DECISION_BADGES = {
  intercept_solution: 'bg-red-900/60 text-red-300',
  threat_assessment: 'bg-orange-900/60 text-orange-300',
  auto_track: 'bg-yellow-900/60 text-yellow-300',
  kill_chain_transition: 'bg-red-900/40 text-red-200',
  replan: 'bg-blue-900/60 text-blue-300',
  comms_fallback: 'bg-amber-900/60 text-amber-300',
  auto_engage: 'bg-red-900/80 text-red-200',
  intercept_complete: 'bg-green-900/60 text-green-300',
}

// `log` is the MISSION LOG, accumulated per frame by useWebSocket
export default function MissionLog({ fleetState, log = [] }) {
  const [expandedId, setExpandedId] = useState(null)
  const scrollRef = useRef(null)

  useEffect(() => {
    scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight)
  }, [log])

  const decisions = (fleetState?.decisions || []).slice().reverse()

  return (
    <div className="border border-slate-700 rounded p-3 bg-slate-900/50 flex flex-col shrink-0">
      <div className="text-xs text-slate-500 mb-2 font-bold tracking-wider">MISSION LOG</div>
      <div ref={scrollRef} className="flex-1 overflow-y-auto text-xs text-slate-400 space-y-0.5 max-h-40">
        {log.length === 0 && <div className="text-slate-600">Waiting for events...</div>}
        {log.map((e) => (
          <div key={e.id}>
            <span className="text-slate-600">{e.ts}</span> {e.msg}
          </div>
        ))}
      </div>

      {decisions.length > 0 && (
        <>
          <div className="text-xs text-slate-500 mt-3 mb-1 font-bold tracking-wider">DECISION TRAIL</div>
          <div className="flex-1 overflow-y-auto text-xs space-y-1 max-h-40">
            {decisions.map((d) => (
              <div
                key={d.id}
                className="cursor-pointer hover:bg-slate-800/50 rounded px-1 py-0.5"
                onClick={() => setExpandedId(expandedId === d.id ? null : d.id)}
              >
                <div className="flex items-center gap-1.5">
                  <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${DECISION_BADGES[d.type] || 'bg-slate-800 text-slate-400'}`}>
                    {d.type.replace(/_/g, ' ').toUpperCase()}
                  </span>
                  <span className={`font-medium ${DECISION_COLORS[d.type] || 'text-slate-300'}`}>{d.action}</span>
                  <span className="text-slate-600 ml-auto">{Math.round(d.confidence * 100)}%</span>
                </div>
                {expandedId === d.id && (
                  <div className="mt-1 ml-2 text-slate-500 text-[11px] leading-relaxed">
                    {d.rationale}
                    {d.assets && d.assets.length > 0 && (
                      <div className="text-slate-600 mt-0.5">Assets: {d.assets.join(', ')}</div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
