import { BrainCircuit, FileSearch, PanelTop, ScanSearch } from 'lucide-react'
import { GlassPanel } from './GlassPanel'
import { useReveal } from './RevealContext'

const actions = [
  { label: 'Analyze Screengrabs', icon: ScanSearch },
  { label: 'Understanding UI', icon: PanelTop },
  { label: 'Diagram Analysis', icon: BrainCircuit },
]

export function VisionPanel() {
  const revealed = useReveal()
  return (
    <GlassPanel className="absolute left-[6.1%] top-[54.5%] z-20 h-[19.7%] w-[17.2%] p-2"
      style={{
        opacity:    revealed ? 1 : 0,
        transform:  revealed ? 'translateY(0)' : 'translateY(14px)',
        transition: 'opacity 0.7s ease 800ms, transform 0.7s ease 800ms',
      }}
    >
      <div className="flex h-full gap-2">
        <div className="flex-1 rounded-[5px] border border-white/14 bg-[#252b38] p-2 shadow-inner">
          <div className="mb-2 h-1.5 w-2/5 rounded-full bg-white/33" />
          <div className="h-[49%] rounded-[3px] border border-white/14 bg-gradient-to-br from-white/8 via-[#4b5368]/80 to-[#191d27]">
            <div className="mx-auto mt-4 h-[25px] w-[70%] border border-white/16 bg-white/5 shadow-[0_0_16px_rgba(255,91,119,0.18)]">
              <div className="h-full bg-gradient-to-t from-[#ff5e6b]/42 to-transparent blur-[0.2px]" />
            </div>
          </div>
          <div className="mt-2 grid grid-cols-3 gap-1.5">
            <span className="h-5 rounded-[2px] border border-white/18 bg-white/7" />
            <span className="h-5 rounded-[2px] border border-white/18 bg-white/7" />
            <span className="h-5 rounded-[2px] border border-white/18 bg-white/7" />
          </div>
          <div className="mt-2 grid grid-cols-3 gap-1">
            <span className="h-1 rounded-full bg-white/25" />
            <span className="h-1 rounded-full bg-white/16" />
            <span className="h-1 rounded-full bg-white/12" />
          </div>
        </div>
        <div className="flex w-[42%] flex-col justify-center gap-2">
          <div className="mx-auto w-[31px] rounded-[4px] border border-white/18 bg-white/84 p-1.5 text-center shadow-lg">
            <FileSearch className="mx-auto h-3.5 w-3.5 text-[#ff4b58]" />
            <div className="mt-1 rounded-[2px] bg-[#f04d58] px-1 text-[7px] font-bold leading-none text-white">PDF</div>
          </div>
          {actions.map((action) => {
            const Icon = action.icon
            return (
              <button
                key={action.label}
                className="flex items-center gap-1 rounded-[5px] border border-white/16 bg-[#1b2029]/88 px-1.5 py-1 text-left font-semibold leading-none text-white/86 shadow-sm [font-size:clamp(7px,0.62cqw,9px)]"
              >
                <Icon className="h-3 w-3 shrink-0 text-white/70" />
                <span>{action.label}</span>
              </button>
            )
          })}
        </div>
      </div>
    </GlassPanel>
  )
}
