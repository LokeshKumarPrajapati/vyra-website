import { useEffect, useRef, useState } from 'react'
import { GeminiLive }   from '../lib/geminiLive'
import { AudioCapture } from '../lib/audioCapture'
import { AudioPlayer }  from '../lib/audioPlayer'

// ── Phase constants ───────────────────────────────────────────────────────────
const IDLE       = 'idle'
const CONNECTING = 'connecting'
const LISTENING  = 'listening'
const SPEAKING   = 'speaking'

export default function VoiceChat({ live2dRef }) {
  const [phase, setPhase] = useState(IDLE)
  const phaseRef    = useRef(IDLE)
  const geminiRef   = useRef(null)
  const captureRef  = useRef(null)
  const playerRef   = useRef(null)
  const lipRafRef   = useRef(null)
  const smoothAmp   = useRef(0)

  function _setPhase(p) { phaseRef.current = p; setPhase(p) }

  // ── Lip sync RAF loop ────────────────────────────────────────────────────
  function _startLipSync() {
    _stopLipSync()
    const tick = () => {
      const amp   = playerRef.current?.getAmplitude() ?? 0
      smoothAmp.current += (amp - smoothAmp.current) * 0.25
      live2dRef?.current?.setMouthOpen(smoothAmp.current)
      lipRafRef.current = requestAnimationFrame(tick)
    }
    lipRafRef.current = requestAnimationFrame(tick)
  }

  function _stopLipSync() {
    if (lipRafRef.current) cancelAnimationFrame(lipRafRef.current)
    lipRafRef.current = null
    smoothAmp.current = 0
    live2dRef?.current?.setMouthOpen(0)
  }

  // ── Full teardown ────────────────────────────────────────────────────────
  function teardown() {
    _stopLipSync()
    captureRef.current?.stop()
    geminiRef.current?.disconnect()
    playerRef.current?.stop()
    captureRef.current = geminiRef.current = playerRef.current = null
    live2dRef?.current?.resumeAutoReact()
    _setPhase(IDLE)
  }

  // ── Start a live voice session ────────────────────────────────────────────
  async function startSession() {
    _setPhase(CONNECTING)
    live2dRef?.current?.pauseAutoReact()

    const player = new AudioPlayer({
      onPlayStart: () => {
        _setPhase(SPEAKING)
        _startLipSync()
      },
      onPlayEnd: () => {
        if (phaseRef.current === SPEAKING) {
          _setPhase(LISTENING)
          _stopLipSync()
        }
      },
    })
    playerRef.current = player

    const gemini = new GeminiLive({
      apiKey: import.meta.env.VITE_GEMINI_API_KEY,
      onAudioChunk:    (b64)  => playerRef.current?.addChunk(b64),
      onTranscription: (text) => {
        const m = text.match(/\[EMOTION:(\w+)\]/i)
        if (m) live2dRef?.current?.triggerEmotion(m[1].toLowerCase())
      },
      onTurnComplete: () => {},
      onError: () => teardown(),
    })
    geminiRef.current = gemini

    const capture = new AudioCapture({
      onChunk: (b64) => geminiRef.current?.sendAudioChunk(b64),
    })
    captureRef.current = capture

    try {
      await gemini.connect()
      await capture.start()
      _setPhase(LISTENING)
    } catch (err) {
      console.error('[VoiceChat] connect failed:', err)
      teardown()
    }
  }

  // Cleanup on unmount
  useEffect(() => () => {
    if (lipRafRef.current) cancelAnimationFrame(lipRafRef.current)
    captureRef.current?.stop()
    geminiRef.current?.disconnect()
    playerRef.current?.stop()
  }, [])

  const active = phase !== IDLE

  return (
    <>
      {/* Inject keyframe CSS once */}
      <style>{`
        @keyframes vc-pulse {
          0%   { transform: scale(1);   opacity: 0.7; }
          100% { transform: scale(1.8); opacity: 0;   }
        }
        @keyframes vc-spin {
          to { transform: rotate(360deg); }
        }
      `}</style>

      <div style={{
        position:       'fixed',
        bottom:         '2rem',
        left:           '50%',
        transform:      'translateX(-50%)',
        zIndex:         200,
        display:        'flex',
        flexDirection:  'column',
        alignItems:     'center',
        gap:            '0.6rem',
        pointerEvents:  'none',
      }}>

        {/* Status label */}
        {active && (
          <div style={{
            pointerEvents:   'none',
            color:           'rgba(255,255,255,0.9)',
            fontSize:        '0.7rem',
            fontFamily:      'system-ui, sans-serif',
            letterSpacing:   '0.08em',
            textTransform:   'uppercase',
            background:      'rgba(0,0,0,0.45)',
            backdropFilter:  'blur(10px)',
            padding:         '0.2rem 0.8rem',
            borderRadius:    '999px',
          }}>
            {phase === CONNECTING ? 'Connecting…'
              : phase === LISTENING ? 'Listening…'
              : 'Speaking…'}
          </div>
        )}

        {/* Pulse ring behind the button */}
        <div style={{ position: 'relative', width: 64, height: 64, pointerEvents: 'auto' }}>
          {(phase === LISTENING || phase === SPEAKING) && (
            <div style={{
              position:     'absolute',
              inset:        0,
              borderRadius: '50%',
              background:   phase === LISTENING
                ? 'rgba(239,68,68,0.5)'
                : 'rgba(37,99,235,0.5)',
              animation:    'vc-pulse 1.4s ease-out infinite',
            }} />
          )}

          {/* Mic button */}
          <button
            onClick={() => active ? teardown() : startSession()}
            title={active ? 'End conversation' : 'Talk to Vyra'}
            style={{
              position:       'relative',
              width:          64,
              height:         64,
              borderRadius:   '50%',
              border:         'none',
              cursor:         'pointer',
              fontSize:       phase === CONNECTING ? '0.9rem' : '1.4rem',
              display:        'flex',
              alignItems:     'center',
              justifyContent: 'center',
              outline:        'none',
              transition:     'background 0.3s ease, box-shadow 0.3s ease',
              background:
                phase === IDLE       ? 'linear-gradient(135deg,#a855f7,#2563eb)'
                : phase === LISTENING  ? 'linear-gradient(135deg,#ef4444,#f97316)'
                : phase === SPEAKING   ? 'linear-gradient(135deg,#2563eb,#7c3aed)'
                :                        'rgba(30,30,30,0.7)',
              boxShadow:
                phase === LISTENING  ? '0 0 0 0 rgba(239,68,68,0), 0 4px 24px rgba(239,68,68,0.55)'
                : phase === SPEAKING ? '0 0 0 0 rgba(37,99,235,0), 0 4px 24px rgba(37,99,235,0.55)'
                :                      '0 4px 20px rgba(168,85,247,0.4)',
            }}
          >
            {phase === CONNECTING
              ? <div style={{ width:22, height:22, borderRadius:'50%', border:'3px solid rgba(255,255,255,0.3)', borderTopColor:'#fff', animation:'vc-spin 0.8s linear infinite' }} />
              : phase === SPEAKING
              ? '♪'
              : '🎤'}
          </button>
        </div>
      </div>
    </>
  )
}
