import { CalendarDays, Code2, Globe2, NotepadText } from 'lucide-react'
import { useReveal } from './RevealContext'

const nodeBase =
  'flex h-[2.55cqw] w-[2.55cqw] min-h-[24px] min-w-[24px] max-h-[34px] max-w-[34px] items-center justify-center rounded-[8px] border border-white/16 shadow-[0_0_16px_rgba(137,92,255,0.24),inset_0_1px_0_rgba(255,255,255,0.14)] backdrop-blur-sm'

const iconMap = {
  code:     <Code2        className="h-[58%] w-[58%] text-[#57c8ff]"  strokeWidth={2.5} />,
  browser:  <Globe2       className="h-[58%] w-[58%] text-[#b8c7ff]"  strokeWidth={2.3} />,
  calendar: <CalendarDays className="h-[58%] w-[58%] text-[#7ee5ff]"  strokeWidth={2.4} />,
  notion:   <NotepadText  className="h-[58%] w-[58%] text-white"       strokeWidth={2.4} />,
}

export function AppNode({ app, delay = 0 }) {
  const revealed = useReveal()
  const isSlack  = app.type === 'slack'
  const isFigma  = app.type === 'figma'

  // Offset from final position to center origin (50vw, 34vh).
  // Using vw/vh since the container is h-screen w-screen.
  const dx = 50 - app.x
  const dy = 34 - app.y

  return (
    <div
      className="absolute z-20 text-center"
      style={{
        left:       `${app.x}%`,
        top:        `${app.y}%`,
        opacity:    revealed ? 1 : 0,
        transform:  revealed
          ? 'translate(-50%, -50%)'
          : `translate(calc(-50% + ${dx}vw), calc(-50% + ${dy}vh))`,
        transition: `transform 0.95s cubic-bezier(0.34,1.4,0.64,1) ${delay}ms, opacity 0.5s ease ${delay}ms`,
        willChange: 'transform, opacity',
      }}
    >
      <div
        className={`${nodeBase} mx-auto bg-[#202535]/72 ${
          app.type === 'calendar'
            ? 'border-cyan-200/28 shadow-[0_0_21px_rgba(91,213,255,0.34),inset_0_1px_0_rgba(255,255,255,0.16)]'
            : ''
        }`}
      >
        {isSlack ? (
          <div className="grid h-[58%] w-[58%] grid-cols-2 gap-[2px]">
            <span className="rounded-full bg-[#2fd188]" />
            <span className="rounded-full bg-[#ffd05c]" />
            <span className="rounded-full bg-[#ff5a7b]" />
            <span className="rounded-full bg-[#69b8ff]" />
          </div>
        ) : isFigma ? (
          <div className="grid h-[66%] w-[44%] grid-cols-2 grid-rows-3 gap-[2px]">
            <span className="rounded-full bg-[#ff5b5b]" />
            <span className="rounded-full bg-[#ffb04d]" />
            <span className="rounded-full bg-[#a96dff]" />
            <span className="rounded-full bg-[#40cfff]" />
            <span className="rounded-full bg-[#28ce7d]" />
            <span />
          </div>
        ) : (
          iconMap[app.type]
        )}
      </div>
      <p className="mt-1 font-semibold leading-none text-white/70 [font-size:clamp(6px,0.5cqw,7.5px)]">
        {app.label}
      </p>
    </div>
  )
}
