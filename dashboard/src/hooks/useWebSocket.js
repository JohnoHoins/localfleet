import { useState, useEffect, useReducer } from 'react'
import { appendTrails, diffFleetEvents } from '../lib/fleetHistory'

const WS_URL = `ws://${window.location.host}/ws`
const MAX_LOG = 100

const INITIAL = { fleetState: null, trails: {}, contactTrails: {}, log: [], logSeq: 0 }

// One frame in, the new fleet state plus everything accumulated from the stream
function frameReducer(state, frame) {
  let { log, logSeq } = state
  const events = diffFleetEvents(state.fleetState, frame)
  if (events.length > 0) {
    log = [...log, ...events.map((e) => ({ ...e, id: ++logSeq }))].slice(-MAX_LOG)
  }
  return {
    fleetState: frame,
    trails: appendTrails(state.trails, frame.assets || [], 'asset_id'),
    contactTrails: appendTrails(state.contactTrails, frame.contacts || [], 'contact_id'),
    log,
    logSeq,
  }
}

// Closing a socket mid-handshake makes the browser log an error; close it once open.
function closeSocket(ws) {
  if (ws.readyState === WebSocket.CONNECTING) {
    ws.onopen = () => ws.close()
  } else {
    ws.close()
  }
}

export default function useWebSocket() {
  const [stream, dispatchFrame] = useReducer(frameReducer, INITIAL)
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    let ws = null
    let reconnectTimer = null
    let closed = false // set on unmount, so this effect stops reconnecting

    function connect() {
      const sock = new WebSocket(WS_URL)
      ws = sock

      sock.onopen = () => setConnected(true)

      sock.onmessage = (event) => {
        if (closed) return
        let frame
        try {
          frame = JSON.parse(event.data)
        } catch {
          return // ignore malformed frames
        }
        dispatchFrame(frame)
      }

      sock.onclose = () => {
        if (closed) return
        setConnected(false)
        reconnectTimer = setTimeout(connect, 1000)
      }

      sock.onerror = () => sock.close()
    }

    connect()
    return () => {
      closed = true
      clearTimeout(reconnectTimer)
      closeSocket(ws)
    }
  }, [])

  return { ...stream, connected }
}
