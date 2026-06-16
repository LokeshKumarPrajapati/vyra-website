import { MousePointer2 } from 'lucide-react'
import { useReveal } from './RevealContext'

const pills = [
  { label: 'Smart Suggestions', x: 46, y: 11, w: 46 },
  { label: 'Guin invanization', x: 18, y: 37, w: 48 },
  { label: 'Smart Suggestions', x: 69, y: 37, w: 48 },
  { label: 'Summarize',         x: 32, y: 60, w: 34 },
  { label: 'Explain',           x: 68, y: 61, w: 30 },
  { label: 'Planner',           x: 34, y: 82, w: 30 },
  { label: 'Choice...',         x: 69, y: 83, w: 31 },
]

export function SuggestionCloud() {
  const revealed = useReveal()
  return (
    <div
      className="absolute left-[9.2%] top-[17.2%] z-30 h-[17.5%] w-[18.4%]"
      style={{
        opacity:    revealed ? 1 : 0,
        transform:  revealed ? 'translateX(0)' : 'translateX(-18px)',
        transition: 'opacity 0.7s ease 550ms, transform 0.7s ease 550ms',
      }}
    >
      {pills.map((pill, i) => (
        <div
          key={`${pill.label}-${i}`}
          className="absolute grid h-[1.42cqw] max-h-[21px] min-h-[18px] -translate-x-1/2 -translate-y-1/2 place-items-center rounded-[5px] border border-white/14 bg-[#191d25]/78 px-1.5 text-center font-semibold leading-none text-white/78 shadow-[0_3px_10px_rgba(0,0,0,0.34),inset_0_1px_0_rgba(255,255,255,0.1)] backdrop-blur-sm [font-size:clamp(7px,0.56cqw,9px)]"
          style={{ left: `${pill.x}%`, top: `${pill.y}%`, width: `${pill.w}%` }}
        >
          {pill.label}
        </div>
      ))}
      <MousePointer2 className="absolute left-[78%] top-[77%] h-[1.3cqw] max-h-[18px] min-h-[14px] w-[1.3cqw] min-w-[14px] max-w-[18px] -rotate-12 text-white/72 drop-shadow-[0_0_7px_rgba(255,255,255,0.35)]" />
      <span className="absolute left-[94.5%] top-[36%] h-[0.72cqw] max-h-[10px] min-h-[7px] w-[0.72cqw] min-w-[7px] max-w-[10px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-[#ffe0ba] shadow-[0_0_11px_rgba(255,210,169,0.9),0_0_22px_rgba(199,116,255,0.42)]" />
    </div>
  )
}
