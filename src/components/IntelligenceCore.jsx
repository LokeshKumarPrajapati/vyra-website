import { apps, memoryLabels } from '../data/ecosystemData'
import { AppNode } from './AppNode'
import { useReveal } from './RevealContext'

const NODE_DELAYS = [150, 230, 310, 390, 470, 550]

export function IntelligenceCore() {
  const revealed = useReveal()

  const axisStyle = {
    opacity:    revealed ? 1 : 0,
    transition: 'opacity 0.8s ease 250ms',
  }

  const memBoxStyle = {
    opacity:    revealed ? 1 : 0,
    transform:  revealed ? 'scale(1)' : 'scale(0.85)',
    transition: 'opacity 0.7s ease 250ms, transform 0.7s cubic-bezier(0.34,1.2,0.64,1) 250ms',
  }

  return (
    <div className="absolute inset-0 z-0">
      <div
        className="absolute left-[50%] top-[40.8%] z-10 h-[39%] w-px bg-gradient-to-b from-transparent via-cyan-100/28 to-transparent shadow-[0_0_12px_rgba(119,226,255,0.22)]"
        style={axisStyle}
      />
      <span
        className="absolute left-[50%] top-[39.1%] z-20 h-[0.55cqw] max-h-[8px] min-h-[5px] w-[0.55cqw] min-w-[5px] max-w-[8px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-cyan-100/90 shadow-[0_0_13px_rgba(117,230,255,0.62)]"
        style={{ opacity: revealed ? 1 : 0, transition: 'opacity 0.6s ease 400ms' }}
      />
      <span
        className="absolute left-[50%] top-[49.8%] z-20 h-[0.5cqw] max-h-[7px] min-h-[5px] w-[0.5cqw] min-w-[5px] max-w-[7px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-[#ffe3c2]/85 shadow-[0_0_12px_rgba(255,208,171,0.58)]"
        style={{ opacity: revealed ? 1 : 0, transition: 'opacity 0.6s ease 450ms' }}
      />
      <span
        className="absolute left-[50%] top-[66.8%] z-20 h-[0.5cqw] max-h-[7px] min-h-[5px] w-[0.5cqw] min-w-[5px] max-w-[7px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-violet-100/80 shadow-[0_0_12px_rgba(199,164,255,0.58)]"
        style={{ opacity: revealed ? 1 : 0, transition: 'opacity 0.6s ease 500ms' }}
      />

      {apps.map((app, i) => (
        <AppNode key={app.label} app={app} delay={NODE_DELAYS[i]} />
      ))}

      <div
        className="absolute left-[38.6%] top-[49.2%] z-20 w-[22.6%] rounded-[9px] border border-white/22 bg-[#060811]/18 py-2 text-center shadow-[0_0_26px_rgba(210,84,255,0.16),inset_0_1px_0_rgba(255,255,255,0.08)] backdrop-blur-sm"
        style={memBoxStyle}
      >
        <p className="font-semibold leading-none text-white/95 [font-size:clamp(11px,1.02cqw,15px)]">Understanding</p>
        <p className="mt-3 font-semibold leading-none text-white/86 [font-size:clamp(10px,0.98cqw,14px)]">
          Persistent Memory System
        </p>
      </div>

      {memoryLabels.map((item, i) => (
        <div
          key={`${item.title}-${item.x}`}
          className="absolute z-20 -translate-x-1/2 rounded-[7px] border border-white/12 bg-[#060811]/24 px-2 py-1 text-center font-semibold leading-tight text-white/72 shadow-[0_0_18px_rgba(117,230,255,0.07),inset_0_1px_0_rgba(255,255,255,0.07)] backdrop-blur-[2px] [font-size:clamp(6px,0.54cqw,8px)]"
          style={{
            left:       `${item.x}%`,
            top:        `${item.y}%`,
            opacity:    revealed ? 1 : 0,
            transform:  revealed ? 'translateX(-50%) translateY(0)' : 'translateX(-50%) translateY(10px)',
            transition: `opacity 0.6s ease ${350 + i * 70}ms, transform 0.6s ease ${350 + i * 70}ms`,
          }}
        >
          <p>{item.title}</p>
          <p className="text-white/68">{item.subtitle}</p>
        </div>
      ))}
    </div>
  )
}
