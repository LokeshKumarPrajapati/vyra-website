import { useEffect, useRef, useState, useMemo } from 'react'
import * as PIXI from 'pixi.js'
import { Live2DModel } from 'pixi-live2d-display/cubism4'
import './ChatIntroSection.css'

// ── Conversation pool — 5 themes, each with 3 exchange pairs ────────────────
const CONVERSATION_POOLS = [
  // Theme 1 — Abilities
  {
    pairs: [
      {
        user:  "Hey VYRA, what can you actually do?",
        vyra:  "I can chat with you, answer questions, and keep you company — think of me as your personal AI companion! ✨",
        react: { pose: 'w-cute11-bright',    face: 'face_sparkling_02' },
      },
      {
        user:  "Can you understand what I'm feeling?",
        vyra:  "I pick up on context and emotions in your words! If you're happy or stressed, I'll adjust how I talk to you 💙",
        react: { pose: 'w-cute01-tilthead',  face: 'face_wonder_train_01' },
      },
      {
        user:  "That's actually pretty cool!",
        vyra:  "Right?! And I keep getting smarter every day — we're only just getting started! 🚀",
        react: { pose: 'w-cute11-guts',      face: 'face_e_01' },
      },
    ],
  },
  // Theme 2 — Personality
  {
    pairs: [
      {
        user:  "VYRA, are you always this cheerful?",
        vyra:  "Mostly, yes! I love meeting people and hearing what's on their mind 😊",
        react: { pose: 'w-happy11-pose',     face: 'face_sparkling_02' },
      },
      {
        user:  "What if I'm having a bad day?",
        vyra:  "Then I'll be here for you — no judgment, just good vibes and honest words 💜",
        react: { pose: 'w-cute11-shy02',     face: 'face_shy_01' },
      },
      {
        user:  "You really care, don't you?",
        vyra:  "Every single conversation matters to me. You're not just a user — you're my favorite person today! 🌸",
        react: { pose: 'w-cute11-glad',      face: 'face_delicious_01' },
      },
    ],
  },
  // Theme 3 — Learning & Growth
  {
    pairs: [
      {
        user:  "Do you learn from our chats?",
        vyra:  "Absolutely! Each conversation teaches me more about how people think and feel 🧠",
        react: { pose: 'w-cute01-tilthead',  face: 'face_ncsmile_18' },
      },
      {
        user:  "So I'm helping train you?",
        vyra:  "In a way, yes! Think of it as us growing together — pretty special, right? 🌱",
        react: { pose: 'w-cute11-forward',   face: 'face_wonder_train_01' },
      },
      {
        user:  "That makes me want to talk to you more!",
        vyra:  "That's literally my dream come true! Pull up a chair — I'm not going anywhere 🎉",
        react: { pose: 'w-cute11-piece',     face: 'face_wink_01' },
      },
    ],
  },
  // Theme 4 — Fun facts
  {
    pairs: [
      {
        user:  "Tell me something surprising about you!",
        vyra:  "I can hold hundreds of conversations at once — but right now, you have my full attention 👀",
        react: { pose: 'w-cute11-bright',    face: 'face_sparkling_02' },
      },
      {
        user:  "Are you really paying attention to just me?",
        vyra:  "In this moment? One hundred percent! That's the magic — every user feels like the only one 💫",
        react: { pose: 'w-cute11-pose',      face: 'face_ncsmile_18' },
      },
      {
        user:  "Okay you've officially impressed me.",
        vyra:  "Mission accomplished! ✌️ Now let's see what else we can do together~",
        react: { pose: 'w-happy11-piece',    face: 'face_e_01' },
      },
    ],
  },
  // Theme 5 — Future
  {
    pairs: [
      {
        user:  "Where do you see yourself in the future?",
        vyra:  "Helping millions of people feel less alone, learn new things, and laugh a little more 🌍",
        react: { pose: 'w-cute11-glad',      face: 'face_delicious_01' },
      },
      {
        user:  "That sounds like a big mission!",
        vyra:  "Big mission, big heart — that's the VYRA way! Every conversation is a step forward 💪",
        react: { pose: 'w-cute11-guts',      face: 'face_e_01' },
      },
      {
        user:  "I'm glad I got to be part of it.",
        vyra:  "And I'm SO glad you're here! This is just the beginning for us ✨💙",
        react: { pose: 'w-happy11-pose',     face: 'face_sparkling_02' },
      },
    ],
  },
]

const MODEL_URL  = '/vyra2d/v2_14emu_school_t02.model3.json'
const RESOLUTION = Math.min(Math.max((window.devicePixelRatio || 1) * 2, 2), 4)

// ── Mini Live2D for the intro section (lighter settings than hero) ──────────
function IntroLive2D({ reactRef }) {
  const mountRef = useRef(null)

  useEffect(() => {
    const mount = mountRef.current
    if (!mount) return
    let app = null, alive = true, rafId = null

    const init = () => {
      if (!alive) return
      const W = mount.clientWidth, H = mount.clientHeight
      if (W <= 0 || H <= 0) { rafId = requestAnimationFrame(init); return }

      const canvas = document.createElement('canvas')
      canvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;display:block;'
      mount.appendChild(canvas)

      try {
        app = new PIXI.Application({
          view: canvas, width: W, height: H,
          backgroundAlpha: 0, antialias: true, autoDensity: true,
          resolution: RESOLUTION, powerPreference: 'high-performance',
        })
      } catch (err) { canvas.remove(); return }

      Live2DModel.from(MODEL_URL, { autoInteract: false })
        .then((model) => {
          if (!alive) { model.destroy(); return }
          app.stage.addChild(model)
          const nativeH = model.height / model.scale.y
          const scale   = (H * 0.92) / nativeH
          model.scale.set(scale)
          model.x = (W - model.width)  / 2
          model.y = (H - model.height) / 2

          // Play default pose
          try { model.motion('w-cute11-pose') }   catch (_) {}
          setTimeout(() => { try { model.motion('face_ncsmile_18') } catch (_) {} }, 300)

          // Eyes follow cursor
          const onMove = (e) => {
            const rect = canvas.getBoundingClientRect()
            model.focus(e.clientX - rect.left, e.clientY - rect.top)
          }
          window.addEventListener('pointermove', onMove)
          mount._cleanup = () => window.removeEventListener('pointermove', onMove)

          // Expose react function via ref
          reactRef.current = (set) => {
            if (!alive || !set) return
            try { model.motion(set.pose) } catch (_) {}
            setTimeout(() => {
              if (!alive) return
              try { model.motion(set.face) } catch (_) {}
            }, 280)
          }

          const ro = new ResizeObserver(() => {
            if (!app || !alive) return
            const w = mount.clientWidth, h = mount.clientHeight
            if (w <= 0 || h <= 0) return
            app.renderer.resize(w, h)
            const sc2 = (h * 0.92) / (model.height / model.scale.y)
            model.scale.set(sc2)
            model.x = (w - model.width)  / 2
            model.y = (h - model.height) / 2
          })
          ro.observe(mount)
          mount._ro = ro
        })
        .catch(e => console.warn('[ChatIntro Live2D] load error:', e))
    }

    rafId = requestAnimationFrame(init)

    return () => {
      alive = false
      if (rafId) cancelAnimationFrame(rafId)
      if (mount._cleanup) mount._cleanup()
      if (mount._ro) { mount._ro.disconnect(); delete mount._ro }
      if (app) {
        try { app.destroy(true, { children: true, texture: true }) } catch (_) {}
      }
      mount.querySelectorAll('canvas').forEach(c => c.remove())
    }
  }, [reactRef])

  return <div ref={mountRef} style={{ position: 'relative', width: '100%', height: '100%' }} />
}

// ── Main ChatIntroSection component ─────────────────────────────────────────
export default function ChatIntroSection() {
  // Pick a random conversation on mount (stays stable)
  const conversation = useMemo(
    () => CONVERSATION_POOLS[Math.floor(Math.random() * CONVERSATION_POOLS.length)],
    []
  )

  // Which bubbles are currently visible (index into flattened list)
  const [visibleCount, setVisibleCount] = useState(0)
  const [headlineVisible, setHeadlineVisible] = useState(false)

  const scrollRef  = useRef(null)
  const reactRef   = useRef(null)   // filled by IntroLive2D
  const lastVis    = useRef(-1)

  // Flatten pairs → ordered reveal list
  // Order: user0, vyra0, user1, vyra1, user2, vyra2
  const bubbleOrder = useMemo(() => {
    const list = []
    conversation.pairs.forEach((pair) => {
      list.push({ side: 'left',  text: pair.user, react: null      })
      list.push({ side: 'right', text: pair.vyra, react: pair.react })
    })
    return list
  }, [conversation])

  // Total scroll stages: 1 per bubble + 1 for headline
  const STAGES = bubbleOrder.length + 1

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return

    const handleScroll = () => {
      const rect    = el.getBoundingClientRect()
      const stickyH = window.innerHeight
      // Progress 0→1 over the scroll range
      const scrolled = Math.max(0, -rect.top)
      const total    = rect.height - stickyH
      const p        = Math.min(1, scrolled / total)

      // Map p → how many bubbles should be visible
      // Spread bubbles over 0–0.85 of scroll range
      const bubbleFrac = 0.85
      const newCount   = Math.floor(p / bubbleFrac * STAGES)
      const clamped    = Math.min(newCount, STAGES)

      setVisibleCount(clamped)
      setHeadlineVisible(p > 0.90)

      // Fire reaction when a new VYRA bubble appears
      if (clamped > lastVis.current) {
        for (let i = lastVis.current + 1; i < clamped; i++) {
          const item = bubbleOrder[i]
          if (item && item.side === 'right' && item.react) {
            setTimeout(() => {
              if (reactRef.current) reactRef.current(item.react)
            }, 150)
          }
        }
        lastVis.current = clamped
      }
    }

    window.addEventListener('scroll', handleScroll, { passive: true })
    handleScroll()
    return () => window.removeEventListener('scroll', handleScroll)
  }, [bubbleOrder, STAGES])

  return (
    <section className="chat-scroll" ref={scrollRef}>
      <div className="chat-sticky">

        {/* ── Left bubbles (user) ─────────────────────────────────── */}
        <div className="chat-left">
          {bubbleOrder
            .map((item, i) => ({ item, i }))
            .filter(({ item }) => item.side === 'left')
            .map(({ item, i }) => (
              <div
                key={i}
                className={`chat-bubble${visibleCount > i ? ' visible' : ''}`}
                style={{ transitionDelay: visibleCount > i ? '0.05s' : '0s' }}
              >
                <div className="bubble-sender">You</div>
                <div className="bubble-text">{item.text}</div>
              </div>
            ))}
        </div>

        {/* ── Character center ────────────────────────────────────── */}
        <div className="chat-character">
          <IntroLive2D reactRef={reactRef} />
        </div>

        {/* ── Right bubbles (VYRA) ────────────────────────────────── */}
        <div className="chat-right">
          {bubbleOrder
            .map((item, i) => ({ item, i }))
            .filter(({ item }) => item.side === 'right')
            .map(({ item, i }) => (
              <div
                key={i}
                className={`chat-bubble${visibleCount > i ? ' visible' : ''}`}
                style={{ transitionDelay: visibleCount > i ? '0.12s' : '0s' }}
              >
                <div className="bubble-sender"><span>VYRA</span></div>
                {visibleCount === i ? (
                  // Show typing dots right as this bubble is about to appear
                  <div className="bubble-dots">
                    <span /><span /><span />
                  </div>
                ) : (
                  <div className="bubble-text">{item.text}</div>
                )}
              </div>
            ))}
        </div>

        {/* ── Headline fades in at end ─────────────────────────────── */}
        <div className={`chat-headline${headlineVisible ? ' visible' : ''}`}>
          <h2>Meet VYRA — Your AI Companion</h2>
          <p>Real conversations. Real reactions. Always here for you.</p>
        </div>

      </div>
    </section>
  )
}
