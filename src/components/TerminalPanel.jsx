import { GlassPanel } from './GlassPanel'
import { useReveal } from './RevealContext'

export function TerminalPanel() {
  const revealed = useReveal()
  return (
    <GlassPanel className="absolute left-[69.7%] top-[21.8%] z-20 h-[22.4%] w-[19.2%] overflow-hidden p-0"
      style={{
        opacity:    revealed ? 1 : 0,
        transform:  revealed ? 'translateX(0)' : 'translateX(14px)',
        transition: 'opacity 0.7s ease 1300ms, transform 0.7s ease 1300ms',
      }}
    >
      <div className="flex h-[20px] items-center gap-1.5 border-b border-white/8 bg-white/9 px-2">
        <span className="h-1.5 w-1.5 rounded-full bg-[#ff6a5f]" />
        <span className="h-1.5 w-1.5 rounded-full bg-[#ffcb5b]" />
        <span className="h-1.5 w-1.5 rounded-full bg-[#53df83]" />
        <span className="ml-auto h-1.5 w-1/3 rounded-full bg-white/15" />
      </div>
      <div className="p-3 font-mono">
        <p className="font-semibold leading-none text-white/80 [font-size:clamp(10px,0.92cqw,14px)]">$ _</p>
        <div className="mt-6 w-[62%] rounded-[5px] border border-white/10 bg-[#111821]/88 p-2 shadow-[0_0_18px_rgba(77,213,255,0.08)]">
          {['Opening Apps...', '+ Running Code.', '+ Execute Commands'].map((line, index) => (
            <p
              key={line}
              className={`leading-tight [font-size:clamp(7px,0.56cqw,8.5px)] ${
                index === 0 ? 'text-white/70' : 'text-[#72ffa0]'
              }`}
            >
              {line}
            </p>
          ))}
        </div>
      </div>
    </GlassPanel>
  )
}
