import { useEffect, useRef, useState } from 'react'
import Navbar from './Navbar'
import Live2DViewer from './Live2DViewer'
import VoiceChat from './VoiceChat'
import './HeroSection.css'

// ─── helpers ──────────────────────────────────────────────────────────────────
const lerp = (a, b, t) => a + (b - a) * t
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v))
const prog = (t, s, e) => clamp((t - s) / (e - s), 0, 1)


export default function HeroSection() {
  const live2dRef = useRef(null)

  // ── Smooth scroll progress (0 → 1) via continuous lerp loop ───────────────
  const [p, setP] = useState(0)
  const scrollTargetRef = useRef(0)   // raw scroll target
  const smoothRef = useRef(0)   // current smooth value
  const rafRef = useRef(null)

  // Capture raw scroll without setState (no jitter)
  useEffect(() => {
    const onScroll = () => { scrollTargetRef.current = window.scrollY }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  // Smooth lerp loop — runs every frame, interpolates toward target
  useEffect(() => {
    const MAX = window.innerHeight * 1.8

    const loop = () => {
      const targetP = clamp(scrollTargetRef.current / MAX, 0, 1)
      const curr = smoothRef.current
      // Lerp factor 0.075 = silky smooth with very little lag
      const next = curr + (targetP - curr) * 0.075

      if (Math.abs(next - curr) > 0.00005) {
        smoothRef.current = next
        setP(next)
      }

      rafRef.current = requestAnimationFrame(loop)
    }

    rafRef.current = requestAnimationFrame(loop)
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current) }
  }, [])

  // ── Phase 1 (p 0 → 0.42): curtains slide apart + character zooms out ──────
  const curtainP = prog(p, 0, 0.42)
  const topCurtainY = lerp(0, -100, curtainP)
  const bottomCurtainY = lerp(0, 100, curtainP)
  const charScale = lerp(3.5, 1.0, curtainP)
  const charTopBase = lerp(80, 8, curtainP)

  // ── Background dark → light (starts once curtains mostly open) ─────────────
  const bgP = prog(p, 0.38, 0.75)
  const r = Math.round(lerp(2, 240, bgP))
  const g = Math.round(lerp(5, 242, bgP))
  const b = Math.round(lerp(20, 252, bgP))
  const bgColor = `rgb(${r},${g},${b})`

  // ── Peek glow fades as curtains open ──────────────────────────────────────
  const peekGlowOp = 1 - prog(p, 0.05, 0.38)

  // ── Phase 2 (p 0.42 → 0.82): character rises to final position ────────────
  const charRiseP = prog(p, 0.42, 0.82)
  const charTop = charTopBase + lerp(0, -16, charRiseP)

  // ── Navbar fades in after curtains fully open ─────────────────────────────
  const navP = prog(p, 0.52, 0.72)

  return (
    <div className="hero-scroll-container">
      <div className="hero-sticky">

        {/* Background colour */}
        <div className="hero-bg" style={{ backgroundColor: bgColor }} />

        {/* Blue aura glow behind character face */}
        <div className="peek-glow" style={{ opacity: peekGlowOp, pointerEvents: 'none' }} />


        {/* Live2D character */}
        <div
          className="character-wrapper"
          style={{
            transform: `translateX(-50%) translateY(${charTop}vh) scale(${charScale})`,
          }}
        >
          <div className="character-inner">
            <Live2DViewer controlRef={live2dRef} />
          </div>
        </div>

        {/* TOP curtain — slides up on scroll */}
        <div
          className="top-curtain"
          style={{ transform: `translateY(${topCurtainY}%)`, pointerEvents: 'none' }}
        />

        {/* BOTTOM curtain — slides down on scroll */}
        <div
          className="bottom-curtain"
          style={{ transform: `translateY(${bottomCurtainY}%)`, pointerEvents: 'none' }}
        />


        {/* Navbar */}
        <Navbar progress={navP} />

      </div>

      {/* Floating voice chat button — outside sticky so it stays fixed */}
      <VoiceChat live2dRef={live2dRef} />
    </div>
  )
}
