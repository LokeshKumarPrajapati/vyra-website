import { Search } from 'lucide-react'
import { useReveal } from './RevealContext'

export function CommandLayer() {
  const revealed = useReveal()
  return (
    <div className="absolute left-[50.0%] top-[78.7%] z-30 w-[19.6%] -translate-x-1/2"
      style={{
        opacity:    revealed ? 1 : 0,
        transform:  revealed ? 'translateX(-50%) translateY(0)' : 'translateX(-50%) translateY(10px)',
        transition: 'opacity 0.7s ease 2000ms, transform 0.7s ease 2000ms',
      }}
    >
      <div className="flex h-[2.18cqw] max-h-[27px] min-h-[22px] items-center gap-2 rounded-[8px] border border-white/15 bg-[#2a303a]/76 px-3 shadow-[0_0_20px_rgba(118,114,255,0.18),inset_0_1px_0_rgba(255,255,255,0.09)] backdrop-blur-md">
        <Search className="h-3.5 w-3.5 text-white/55" />
        <span className="font-medium text-white/47 [font-size:clamp(8px,0.62cqw,9px)]">command...</span>
      </div>
    </div>
  )
}
