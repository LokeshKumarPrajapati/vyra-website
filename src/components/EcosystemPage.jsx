import { CommandLayer } from './CommandLayer'
import { ConnectorLayer } from './ConnectorLayer'
import { HeroHeader } from './HeroHeader'
import { IntelligenceCore } from './IntelligenceCore'
import { PillCluster } from './PillCluster'
import { SectionLabel } from './SectionLabel'
import { TerminalPanel } from './TerminalPanel'
import { VisionPanel } from './VisionPanel'
import { AgentCluster } from './AgentCluster'
import { ProactivePanel } from './ProactivePanel'
import { WorkflowChain } from './WorkflowChain'
import { SuggestionCloud } from './SuggestionCloud'
import SoftAurora from './SoftAurora'
import { contextChips } from '../data/ecosystemData'
import { useEffect, useState } from 'react'
import { useReveal } from './RevealContext'

export function EcosystemPage() {
  const revealed = useReveal()
  const [auroraReady, setAuroraReady] = useState(false)

  useEffect(() => {
    if (!revealed) return
    const t = setTimeout(() => setAuroraReady(true), 1500)
    return () => clearTimeout(t)
  }, [revealed])

  return (
    <div className="relative h-full w-full overflow-hidden bg-[#07080d]">
      <div className="vyra-scene">
        <div className="absolute inset-0 z-0 bg-[#03050b]"
          style={{
            opacity:    auroraReady ? 1 : 0,
            transition: auroraReady ? 'opacity 1.5s ease' : 'none',
          }}
        >
          <SoftAurora
            speed={0.6}
            scale={1.5}
            brightness={1}
            color1="#f7f7f7"
            color2="#e100ff"
            noiseFrequency={2.5}
            noiseAmplitude={1}
            bandHeight={0.5}
            bandSpread={1}
            octaveDecay={0.1}
            layerOffset={0}
            colorSpeed={1}
            enableMouseInteraction
            mouseInfluence={0.25}
          />
        </div>
        <div className="absolute inset-0 z-[1] bg-[radial-gradient(ellipse_at_center,rgba(4,8,18,0.03),rgba(0,0,0,0.28)_72%,rgba(0,0,0,0.56)),linear-gradient(180deg,rgba(0,0,0,0.21),rgba(0,0,0,0.1)_42%,rgba(0,0,0,0.29))]" />
        <div className="pointer-events-none absolute inset-[7px] z-[2] rounded-[11px] border border-white/[0.035] shadow-[inset_0_0_28px_rgba(0,0,0,0.32)]" />
        <div className="absolute inset-y-0 right-[1%] z-40 flex items-center">
          <span className="h-[14%] w-[2px] rounded-full bg-white/16" />
        </div>
        <HeroHeader />
        <IntelligenceCore />
        <ConnectorLayer />
        <SuggestionCloud />
        <PillCluster chips={contextChips} />
        <SectionLabel title="Cursor Intelligence" className="left-[12.4%] top-[35.7%] w-[15.5%]" align="center" direction="left" delay={700}>
          AI attached to your workflow. Text, Explain, Smart Suggestion prompts.
        </SectionLabel>
        <SectionLabel title="Context Awareness Engine" className="left-[10.4%] top-[45%] w-[17.2%]" align="center" direction="left" delay={750}>
          Vyra doesn't start and recent, files, current files a single workflow.
        </SectionLabel>
        <VisionPanel />
        <SectionLabel title="Vision Intelligence & Desktop Layer" className="left-[7%] top-[79.7%] w-[21.5%]" direction="up" delay={900}>
          Point, highlight, or screenshot. If it's on your screen, Vyra understands, and applications.
        </SectionLabel>
        <CommandLayer />
        <SectionLabel title="Universal Command Layer" className="left-[40.6%] top-[84.4%] w-[19%]" align="center" direction="up" delay={2000}>
          One command control starts to runs commands, apps, files, data, and workflows
        </SectionLabel>
        <TerminalPanel />
        <WorkflowChain />
        <SectionLabel title="Computer Control & Workflow Automation Engine" className="left-[70%] top-[48.5%] w-[20.8%]" direction="right" delay={1500}>
          Vyra beyond chat. Vyra manages action files, controls your browser, and runs commands to get the job done.
        </SectionLabel>
        <AgentCluster />
        <SectionLabel title="Multi-Agent Collaboration" className="left-[62%] top-[84%] w-[19%]" direction="right" delay={2100}>
          Specialized agents working together Research, Coding, Design, and more.
        </SectionLabel>
        <ProactivePanel />
        <SectionLabel title="Proactive Intelligence" className="left-[82.5%] top-[80.8%] w-[15.5%]" direction="right" delay={2200}>
          Anticipates needs, notices work style actions, making type feel intelligent.
        </SectionLabel>

      </div>
    </div>
  )
}
