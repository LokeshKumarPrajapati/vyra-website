import { BarChart3, Download, Mail } from 'lucide-react'
import { workflowSteps } from '../data/ecosystemData'
import { useReveal } from './RevealContext'

const icons = {
  download: Download,
  analyze: BarChart3,
  mail: Mail,
}

const tones = {
  download: 'from-[#0f78df] to-[#50c8ff]',
  analyze: 'from-[#2ba76d] to-[#79e778]',
  mail: 'from-[#744fc7] to-[#d697ff]',
}

export function WorkflowChain() {
  const revealed = useReveal()
  return (
    <div className="absolute left-[82.3%] top-[38.8%] z-20 flex -translate-x-1/2 items-center gap-1.5">
      {workflowSteps.map((step, index) => {
        const Icon = icons[step.icon]
        const delay = 1500 + index * 120
        return (
          <div key={step.label} className="flex items-center gap-2"
            style={{
              opacity:    revealed ? 1 : 0,
              transform:  revealed ? 'translateY(0)' : 'translateY(10px)',
              transition: `opacity 0.6s ease ${delay}ms, transform 0.6s ease ${delay}ms`,
            }}
          >
            <div className="text-center">
              <div className={`grid h-[2.28cqw] max-h-[29px] min-h-[23px] w-[2.28cqw] min-w-[23px] max-w-[29px] place-items-center rounded-[7px] border border-white/14 bg-gradient-to-br ${tones[step.icon]} shadow-[0_0_18px_rgba(88,182,255,0.22)]`}>
                <Icon className="h-[58%] w-[58%] text-white" strokeWidth={2.4} />
              </div>
              <p className="mt-1 font-semibold text-white/75 [font-size:clamp(6px,0.5cqw,8px)]">{step.label}</p>
            </div>
            {index < workflowSteps.length - 1 && <span className="mb-4 text-white/55">→</span>}
          </div>
        )
      })}
    </div>
  )
}
