import { useState } from 'react'
import { agents } from '../data/ecosystemData'
import { Bot, Code2, FlaskConical, PenTool, Search } from 'lucide-react'
import { useReveal } from './RevealContext'

const agentIcons = {
  Researcher: Search,
  Planner:    FlaskConical,
  Coder:      Code2,
  Designer:   PenTool,
  Automator:  Bot,
}

// Map gradient classes → real glow colours
const agentGlow = {
  Researcher: 'rgba(95,216,255,0.75)',
  Planner:    'rgba(255,190,80,0.70)',
  Coder:      'rgba(87,200,255,0.70)',
  Designer:   'rgba(196,125,255,0.70)',
  Automator:  'rgba(80,220,160,0.70)',
}

export function AgentCluster() {
  const [hovered, setHovered] = useState(null)
  const revealed = useReveal()

  return (
    <div className="absolute inset-0 z-20">
      {/* Grid decoration */}
      <div className="absolute left-[68.8%] top-[71%] grid h-[3.6cqw] max-h-[44px] min-h-[34px] w-[4.1cqw] min-w-[41px] max-w-[50px] grid-cols-3 gap-1 rounded-[6px] border border-white/12 bg-[#242135]/66 p-1 shadow-[0_0_22px_rgba(164,102,255,0.15)]"
        style={{
          opacity:    revealed ? 1 : 0,
          transition: 'opacity 0.6s ease 1700ms',
        }}
      >
        {Array.from({ length: 9 }).map((_, i) => (
          <span key={i} className="rounded-[2px] border border-white/10 bg-white/8" />
        ))}
      </div>

      {agents.map((agent, agentIdx) => {
        const Icon  = agentIcons[agent.label]
        const glow  = agentGlow[agent.label] ?? 'rgba(137,92,255,0.6)'
        const isHov = hovered === agent.label

        return (
          <div
            key={agent.label}
            className="absolute -translate-x-1/2 -translate-y-1/2 text-center cursor-pointer"
            style={{
              left:       `${agent.x}%`,
              top:        `${agent.y}%`,
              opacity:    revealed ? 1 : 0,
              transform:  revealed ? 'translateX(-50%) translateY(-50%) scale(1)' : 'translateX(-50%) translateY(-50%) scale(0.7)',
              transition: `opacity 0.5s ease ${1700 + agentIdx * 100}ms, transform 0.5s cubic-bezier(0.34,1.4,0.64,1) ${1700 + agentIdx * 100}ms`,
            }}
            onMouseEnter={() => setHovered(agent.label)}
            onMouseLeave={() => setHovered(null)}
          >


            {/* Idle ambient glow */}
            <div style={{
              position:      'absolute',
              inset:         '-4px',
              borderRadius:  '50%',
              background:    glow,
              opacity:       isHov ? 0 : 0.14,
              filter:        'blur(5px)',
              animation:     `agent-pulse-${agent.label} 3s ease-in-out infinite`,
              pointerEvents: 'none',
            }} />

            {/* Agent icon circle */}
            <div
              className={`mx-auto grid place-items-center rounded-full border border-white/24 bg-gradient-to-br ${agent.tone}`}
              style={{
                width:      'clamp(18px,1.78cqw,21px)',
                height:     'clamp(18px,1.78cqw,21px)',
                boxShadow:  isHov
                  ? `0 0 30px ${glow}, 0 0 10px ${glow}, inset 0 1px 0 rgba(255,255,255,0.3)`
                  : `0 0 15px rgba(255,255,255,0.16)`,
                transform:  isHov ? 'scale(1.25) translateY(-2px)' : 'scale(1)',
                transition: 'all 0.22s cubic-bezier(0.34,1.56,0.64,1)',
                border:     isHov ? `1px solid ${glow}` : '1px solid rgba(255,255,255,0.24)',
              }}
            >
              <Icon
                style={{
                  width:  '52%',
                  height: '52%',
                  color:  isHov ? '#fff' : 'rgba(255,255,255,0.88)',
                  filter: isHov ? `drop-shadow(0 0 4px ${glow})` : 'none',
                  transition: 'all 0.2s ease',
                }}
                strokeWidth={2.2}
              />
            </div>

            {/* Label */}
            <p style={{
              marginTop:     '4px',
              fontSize:      'clamp(6px,0.5cqw,8px)',
              fontWeight:    600,
              lineHeight:    1,
              color:         isHov ? 'rgba(255,255,255,0.98)' : 'rgba(255,255,255,0.78)',
              transition:    'color 0.2s ease',
              letterSpacing: '0.04em',
            }}>
              {agent.label}
            </p>

            {/* Tooltip */}
            {isHov && (
              <div style={{
                position:      'absolute',
                bottom:        'calc(100% + 10px)',
                left:          '50%',
                transform:     'translateX(-50%)',
                background:    'rgba(8,10,24,0.94)',
                border:        `1px solid ${glow}`,
                borderRadius:  '6px',
                padding:       '3px 9px',
                whiteSpace:    'nowrap',
                fontSize:      '7px',
                fontWeight:    600,
                color:         'rgba(255,255,255,0.92)',
                boxShadow:     `0 4px 20px rgba(0,0,0,0.5)`,
                pointerEvents: 'none',
                zIndex:        50,
                animation:     'tooltip-pop 0.15s ease',
              }}>
                {agent.label} Agent
              </div>
            )}
          </div>
        )
      })}

      <style>{`
        @keyframes agent-pulse-Researcher { 0%,100%{opacity:.12} 50%{opacity:.26} }
        @keyframes agent-pulse-Planner    { 0%,100%{opacity:.10} 50%{opacity:.22} }
        @keyframes agent-pulse-Coder      { 0%,100%{opacity:.12} 50%{opacity:.24} }
        @keyframes agent-pulse-Designer   { 0%,100%{opacity:.10} 50%{opacity:.22} }
        @keyframes agent-pulse-Automator  { 0%,100%{opacity:.12} 50%{opacity:.26} }
        @keyframes tooltip-pop {
          from { opacity:0; transform:translateX(-50%) translateY(5px); }
          to   { opacity:1; transform:translateX(-50%) translateY(0);   }
        }
      `}</style>
    </div>
  )
}
