import { useEffect, useRef, useState } from 'react'
import { GeminiLive, MODES } from '../lib/geminiLive'
import { AudioCapture }       from '../lib/audioCapture'
import { AudioPlayer }        from '../lib/audioPlayer'

const IDLE       = 'idle'
const CONNECTING = 'connecting'
const LISTENING  = 'listening'
const SPEAKING   = 'speaking'

const MODE_ORDER = ['girlfriend', 'bestfriend', 'professional']

// Emotions to cycle through while Vyra is actively speaking — per mode
const TALKING_POOL = {
  girlfriend:   ['happy', 'loving', 'excited', 'playful', 'caring', 'shy', 'love', 'delighted', 'agreeing'],
  bestfriend:   ['happy', 'excited', 'playful', 'agreeing', 'smug', 'caring', 'curious', 'greeting'],
  professional: ['neutral', 'serious', 'thinking', 'agreeing', 'caring', 'curious', 'relief'],
}

const MODE_COLORS = {
  girlfriend:   { active: 'linear-gradient(135deg,#f472b6,#ec4899)', glow: 'rgba(244,114,182,0.45)', dot: '#f472b6' },
  bestfriend:   { active: 'linear-gradient(135deg,#a78bfa,#7c3aed)', glow: 'rgba(167,139,250,0.45)', dot: '#a78bfa' },
  professional: { active: 'linear-gradient(135deg,#38bdf8,#2563eb)', glow: 'rgba(56,189,248,0.45)',  dot: '#38bdf8' },
}

const MIC_COLORS = {
  idle:       'linear-gradient(135deg,#a855f7,#2563eb)',
  connecting: 'rgba(30,30,30,0.7)',
  listening:  'linear-gradient(135deg,#ef4444,#f97316)',
  speaking:   'linear-gradient(135deg,#2563eb,#7c3aed)',
}

// SVG microphone icon — no emojis
const MicIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="9" y="2" width="6" height="12" rx="3"/>
    <path d="M5 10a7 7 0 0 0 14 0"/>
    <line x1="12" y1="19" x2="12" y2="22"/>
    <line x1="9"  y1="22" x2="15" y2="22"/>
  </svg>
)

const StopIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="white">
    <rect x="4" y="4" width="16" height="16" rx="3"/>
  </svg>
)

const WaveIcon = ({ color }) => (
  <svg width="18" height="12" viewBox="0 0 44 20" fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round">
    <path d="M2 10 Q8 2 14 10 Q20 18 26 10 Q32 2 38 10 Q44 18 50 10"/>
  </svg>
)

export default function VoiceChat({ live2dRef }) {
  const [mode, setMode]   = useState(() => localStorage.getItem('vyra_mode') || 'girlfriend')
  const [phase, setPhase] = useState(IDLE)

  const phaseRef      = useRef(IDLE)
  const geminiRef     = useRef(null)
  const captureRef    = useRef(null)
  const playerRef     = useRef(null)
  const talkCycleRef  = useRef(null)
  const lastTalkEmRef = useRef(null)
  const modeRef       = useRef(mode)
  modeRef.current = mode

  function _setPhase(p) { phaseRef.current = p; setPhase(p) }

  function _startLipSync() {
    live2dRef?.current?.setLipSync(() => playerRef.current?.getAmplitude() ?? 0)
  }

  function _stopLipSync() {
    live2dRef?.current?.clearLipSync()
  }

  function _startTalkCycle() {
    _stopTalkCycle()
    const pool = TALKING_POOL[modeRef.current] ?? TALKING_POOL.girlfriend
    const fire = () => {
      const opts = pool.filter(e => e !== lastTalkEmRef.current)
      const em = opts[Math.floor(Math.random() * opts.length)]
      lastTalkEmRef.current = em
      live2dRef?.current?.triggerEmotion(em)
      talkCycleRef.current = setTimeout(fire, 3000 + Math.random() * 1500)
    }
    talkCycleRef.current = setTimeout(fire, 800)
  }

  function _stopTalkCycle() {
    if (talkCycleRef.current) { clearTimeout(talkCycleRef.current); talkCycleRef.current = null }
    lastTalkEmRef.current = null
  }

  function teardown() {
    _stopLipSync()
    _stopTalkCycle()
    captureRef.current?.stop()
    geminiRef.current?.disconnect()
    playerRef.current?.stop()
    captureRef.current = geminiRef.current = playerRef.current = null
    live2dRef?.current?.resumeAutoReact()
    _setPhase(IDLE)
  }

  async function startSession(targetMode) {
    const m = targetMode ?? mode
    _setPhase(CONNECTING)
    live2dRef?.current?.pauseAutoReact()
    live2dRef?.current?.triggerEmotion('neutral')

    const player = new AudioPlayer({
      onPlayStart: () => { _setPhase(SPEAKING); _startLipSync(); _startTalkCycle() },
      onPlayEnd:   () => { if (phaseRef.current === SPEAKING) { _setPhase(LISTENING); _stopLipSync(); _stopTalkCycle() } },
    })
    playerRef.current = player

    const gemini = new GeminiLive({
      apiKey: import.meta.env.VITE_GEMINI_API_KEY,
      mode: m,
      onAudioChunk:    (b64)  => playerRef.current?.addChunk(b64),
      onTranscription: (text) => {
        const match = text.match(/\[EMOTION:(\w+)\]/i)
        if (match) live2dRef?.current?.triggerEmotion(match[1].toLowerCase())
      },
      onTurnComplete: () => {},
      onError: () => teardown(),
    })
    geminiRef.current = gemini

    captureRef.current = new AudioCapture({
      onChunk: (b64) => geminiRef.current?.sendAudioChunk(b64),
    })

    try {
      await gemini.connect()
      await captureRef.current.start()
      _setPhase(LISTENING)
      gemini.sendGreeting()
    } catch (err) {
      console.error('[VoiceChat] connect failed:', err)
      teardown()
    }
  }

  function switchMode(newMode) {
    localStorage.setItem('vyra_mode', newMode)
    setMode(newMode)
    if (phaseRef.current !== IDLE) {
      teardown()
      setTimeout(() => startSession(newMode), 400)
    }
  }

  useEffect(() => () => {
    live2dRef?.current?.clearLipSync()
    _stopTalkCycle()
    captureRef.current?.stop()
    geminiRef.current?.disconnect()
    playerRef.current?.stop()
  }, [])

  const active  = phase !== IDLE
  const modeClr = MODE_COLORS[mode]

  const statusText =
    phase === CONNECTING ? 'Connecting' :
    phase === LISTENING  ? 'Listening'  :
    phase === SPEAKING   ? 'Speaking'   : ''

  return (
    <>
      <style>{`
        @keyframes vc-pulse  { 0%{transform:scale(1);opacity:.55} 100%{transform:scale(2.4);opacity:0} }
        @keyframes vc-spin   { to{transform:rotate(360deg)} }
        @keyframes vc-wave   { 0%,100%{opacity:.35} 50%{opacity:1} }

        .vc-panel {
          font-family: 'Inter', system-ui, -apple-system, sans-serif;
        }
        .vc-mode-tab {
          padding: 0.28rem 0.85rem;
          border-radius: 6px;
          border: none;
          cursor: pointer;
          font-size: 0.7rem;
          font-weight: 500;
          letter-spacing: 0.045em;
          transition: background 0.18s ease, color 0.18s ease;
          outline: none;
          white-space: nowrap;
          font-family: inherit;
        }
        .vc-mic-btn {
          border: none;
          cursor: pointer;
          outline: none;
          transition: opacity 0.2s ease, transform 0.15s ease;
        }
        .vc-mic-btn:hover  { opacity: 0.9; transform: scale(1.05); }
        .vc-mic-btn:active { transform: scale(0.96); }
      `}</style>

      {/* ── Top-left fixed panel ────────────────────────────────────────────── */}
      <div
        className="vc-panel"
        style={{
          position:      'absolute',
          top:           '24px',
          left:          '24px',
          zIndex:        200,
          display:       'flex',
          flexDirection: 'column',
          gap:           '8px',
          pointerEvents: 'none',
        }}
      >

        {/* ── Mode selector pill ── */}
        <div style={{
          display:        'flex',
          gap:            '3px',
          pointerEvents:  'auto',
          background:     'rgba(255,255,255,0.88)',
          backdropFilter: 'blur(20px) saturate(180%)',
          borderRadius:   '10px',
          padding:        '4px',
          border:         '1px solid rgba(0,0,0,0.07)',
          boxShadow:      '0 2px 14px rgba(0,0,0,0.09)',
        }}>
          {MODE_ORDER.map(m => {
            const isActive = mode === m
            const clr = MODE_COLORS[m]
            return (
              <button
                key={m}
                className="vc-mode-tab"
                onClick={() => switchMode(m)}
                style={{
                  background: isActive ? clr.active : 'transparent',
                  color:      isActive ? '#fff' : 'rgba(0,0,0,0.40)',
                  fontWeight: isActive ? 600 : 400,
                }}
              >
                {MODES[m].label}
              </button>
            )
          })}
        </div>

        {/* ── Mic + status row ── */}
        <div style={{
          display:       'flex',
          alignItems:    'center',
          gap:           '10px',
          pointerEvents: 'auto',
        }}>

          {/* Mic button with pulse ring */}
          <div style={{ position: 'relative', width: 42, height: 42, flexShrink: 0 }}>
            {(phase === LISTENING || phase === SPEAKING) && (
              <div style={{
                position:     'absolute',
                inset:        -6,
                borderRadius: '50%',
                background:   phase === LISTENING ? 'rgba(239,68,68,0.38)' : modeClr.glow,
                animation:    'vc-pulse 1.6s ease-out infinite',
              }} />
            )}
            <button
              className="vc-mic-btn"
              onClick={() => active ? teardown() : startSession()}
              title={active ? 'End conversation' : `Talk to Vyra — ${MODES[mode].label} mode`}
              style={{
                position:       'relative',
                width:           42,
                height:          42,
                borderRadius:   '50%',
                background:     MIC_COLORS[phase],
                display:        'flex',
                alignItems:     'center',
                justifyContent: 'center',
                boxShadow:      active
                  ? `0 4px 18px ${modeClr.glow}`
                  : '0 2px 10px rgba(0,0,0,0.16)',
              }}
            >
              {phase === CONNECTING
                ? <div style={{ width: 16, height: 16, borderRadius: '50%', border: '2.5px solid rgba(255,255,255,0.2)', borderTopColor: '#fff', animation: 'vc-spin .75s linear infinite' }} />
                : active
                  ? <StopIcon />
                  : <MicIcon />
              }
            </button>
          </div>

          {/* Status chip or idle hint */}
          {active ? (
            <div style={{
              display:        'flex',
              alignItems:     'center',
              gap:            '7px',
              background:     'rgba(255,255,255,0.88)',
              backdropFilter: 'blur(20px) saturate(180%)',
              border:         '1px solid rgba(0,0,0,0.07)',
              borderRadius:   '8px',
              padding:        '5px 11px 5px 9px',
              boxShadow:      '0 2px 14px rgba(0,0,0,0.09)',
            }}>
              <span style={{ display: 'flex', alignItems: 'center', animation: 'vc-wave 1.8s ease infinite' }}>
                <WaveIcon color={modeClr.dot} />
              </span>
              <span style={{
                fontSize:      '0.68rem',
                fontWeight:    600,
                letterSpacing: '0.07em',
                textTransform: 'uppercase',
                color:         'rgba(0,0,0,0.50)',
              }}>
                {statusText}
              </span>
            </div>
          ) : (
            <span style={{
              fontSize:      '0.66rem',
              color:         'rgba(0,0,0,0.28)',
              letterSpacing: '0.04em',
              fontWeight:    400,
            }}>
              Tap to talk
            </span>
          )}

        </div>
      </div>
    </>
  )
}
