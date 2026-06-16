import { useReveal } from './RevealContext'

export function FloatingChip({ label, x, y, className = '', delay = 0 }) {
  const revealed = useReveal()
  return (
    <div
      className={`absolute z-20 -translate-x-1/2 -translate-y-1/2 rounded-[5px] border border-white/15 bg-[#191d25]/76 px-2 py-1 text-center font-semibold leading-none text-white/78 shadow-[0_3px_12px_rgba(0,0,0,0.3),inset_0_1px_0_rgba(255,255,255,0.1)] backdrop-blur-sm [font-size:clamp(6px,0.54cqw,8px)] ${className}`}
      style={{
        left:       `${x}%`,
        top:        `${y}%`,
        opacity:    revealed ? 1 : 0,
        transform:  revealed ? 'translate(-50%,-50%) translateY(0)' : 'translate(-50%,-50%) translateY(8px)',
        transition: `opacity 0.5s ease ${delay}ms, transform 0.5s ease ${delay}ms`,
      }}
    >
      {label}
    </div>
  )
}

export function PillCluster({ chips }) {
  return chips.map((chip, i) => (
    <FloatingChip key={`${chip.label}-${chip.x}`} {...chip} delay={650 + i * 80} />
  ))
}
