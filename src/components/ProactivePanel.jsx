import { Bot, Sparkles } from 'lucide-react'
import { useReveal } from './RevealContext'

export function ProactivePanel() {
  const revealed = useReveal()
  return (
    <div className="absolute left-[80%] top-[64.9%] z-20 h-[14%] w-[15.2%]"
      style={{
        opacity:    revealed ? 1 : 0,
        transform:  revealed ? 'translateY(0)' : 'translateY(14px)',
        transition: 'opacity 0.7s ease 1900ms, transform 0.7s ease 1900ms',
      }}
    >
      <div className="absolute left-[23%] top-[-8%] h-[56%] w-[70%] rounded-[7px] border border-white/8 bg-[#151923]/55 shadow-[0_10px_24px_rgba(0,0,0,0.26)] backdrop-blur-md">
        <div className="flex h-[12px] items-center gap-1 border-b border-white/7 px-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-[#ff6d62]" />
          <span className="h-1.5 w-1.5 rounded-full bg-[#ffcc61]" />
          <span className="h-1.5 w-1.5 rounded-full bg-[#57df89]" />
          <span className="ml-auto h-1 w-1/3 rounded-full bg-white/12" />
        </div>
      </div>
      <div className="absolute left-[8%] top-[-4%] h-[25px] w-[45%] rounded-[5px] border border-white/10 bg-[#202530]/82 p-1.5 shadow-lg">
        <div className="flex items-center gap-1.5">
          <Bot className="h-3.5 w-3.5 rounded bg-[#34517f] p-0.5 text-[#bcd8ff]" />
          <p className="font-semibold leading-tight text-white/82 [font-size:clamp(6px,0.46cqw,7.2px)]">
            Repeated Workflow Detected: Automate?
          </p>
        </div>
      </div>
      <div className="absolute left-[48%] top-[38%] h-[25px] w-[49%] rounded-[5px] border border-white/10 bg-[#202530]/82 p-1.5 shadow-lg">
        <div className="flex items-center gap-1.5">
          <Sparkles className="h-3.5 w-3.5 rounded bg-[#6a48a7] p-0.5 text-[#f3dfff]" />
          <p className="font-semibold leading-tight text-white/82 [font-size:clamp(6px,0.46cqw,7.2px)]">
            Repeated Workflow Detected: Want you to automate?
          </p>
        </div>
      </div>
    </div>
  )
}
