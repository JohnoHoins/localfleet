import { useState, useRef, useCallback } from 'react'

/** Encode Float32 PCM samples into a 16kHz mono WAV blob. */
function encodeWav(samples, sampleRate) {
  if (sampleRate !== 16000) {
    const ratio = sampleRate / 16000
    const newLen = Math.round(samples.length / ratio)
    const resampled = new Float32Array(newLen)
    for (let i = 0; i < newLen; i++) {
      resampled[i] = samples[Math.round(i * ratio)]
    }
    samples = resampled
    sampleRate = 16000
  }

  const buffer = new ArrayBuffer(44 + samples.length * 2)
  const view = new DataView(buffer)

  function writeStr(offset, str) {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i))
  }

  writeStr(0, 'RIFF')
  view.setUint32(4, 36 + samples.length * 2, true)
  writeStr(8, 'WAVE')
  writeStr(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  writeStr(36, 'data')
  view.setUint32(40, samples.length * 2, true)

  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true)
  }

  return new Blob([buffer], { type: 'audio/wav' })
}

export default function VoiceButton({ onResult }) {
  const [recording, setRecording] = useState(false)
  const [disabled, setDisabled] = useState(false)
  const [sending, setSending] = useState(false)
  const [seconds, setSeconds] = useState(0)
  const ctxRef = useRef(null)
  const sourceRef = useRef(null)
  const processorRef = useRef(null)
  const chunksRef = useRef([])
  const streamRef = useRef(null)
  const recordingRef = useRef(false)
  const timerRef = useRef(null)

  async function startRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      const ctx = new AudioContext({ sampleRate: 16000 })
      ctxRef.current = ctx
      const source = ctx.createMediaStreamSource(stream)
      sourceRef.current = source

      const processor = ctx.createScriptProcessor(4096, 1, 1)
      processorRef.current = processor
      chunksRef.current = []

      processor.onaudioprocess = (e) => {
        const data = e.inputBuffer.getChannelData(0)
        chunksRef.current.push(new Float32Array(data))
      }

      source.connect(processor)
      processor.connect(ctx.destination)
      recordingRef.current = true
      setRecording(true)
      setSeconds(0)
      timerRef.current = setInterval(() => setSeconds((s) => s + 1), 1000)
    } catch {
      setDisabled(true)
    }
  }

  const stopRecording = useCallback(async () => {
    if (!recordingRef.current) return
    recordingRef.current = false
    setRecording(false)
    clearInterval(timerRef.current)

    processorRef.current?.disconnect()
    sourceRef.current?.disconnect()
    streamRef.current?.getTracks().forEach((t) => t.stop())
    await ctxRef.current?.close()

    const totalLen = chunksRef.current.reduce((n, c) => n + c.length, 0)
    const merged = new Float32Array(totalLen)
    let offset = 0
    for (const chunk of chunksRef.current) {
      merged.set(chunk, offset)
      offset += chunk.length
    }

    // Need at least 0.5s of audio
    if (merged.length < 8000) {
      onResult?.({ success: false, error: 'Recording too short — click MIC, speak, then click STOP' })
      return
    }

    const wavBlob = encodeWav(merged, 16000)
    setSending(true)
    const form = new FormData()
    form.append('audio', wavBlob, 'voice.wav')

    try {
      const res = await fetch('/api/voice-command', { method: 'POST', body: form })
      const data = await res.json()
      onResult?.(data)
    } catch (err) {
      onResult?.({ success: false, error: err.message })
    } finally {
      setSending(false)
    }
  }, [onResult])

  function handleClick() {
    if (recording) {
      stopRecording()
    } else {
      startRecording()
    }
  }

  if (disabled) {
    return (
      <button
        className="px-3 py-1.5 bg-slate-700 text-slate-500 text-sm rounded font-bold cursor-not-allowed"
        title="Microphone permission denied"
        disabled
      >
        MIC
      </button>
    )
  }

  return (
    <button
      className={`px-3 py-1.5 text-sm rounded font-bold transition-colors select-none min-w-[56px] ${
        recording
          ? 'bg-red-600 text-white animate-pulse'
          : sending
            ? 'bg-yellow-600 text-white'
            : 'bg-slate-700 hover:bg-slate-600 text-slate-200'
      }`}
      onClick={handleClick}
      disabled={sending}
    >
      {recording ? `STOP ${seconds}s` : sending ? '...' : 'MIC'}
    </button>
  )
}
