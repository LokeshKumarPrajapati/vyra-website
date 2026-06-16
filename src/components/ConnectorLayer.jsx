import { connectorLabels } from '../data/ecosystemData'
import { useReveal } from './RevealContext'

const paths = [
  // LEFT INPUT SYSTEM
  { id: 'prompt-cloud-to-left-hub',     d: 'M267 132 C324 132 363 169 410 205', tone: 'pink',   opacity: 0.54 },
  { id: 'recent-project-to-left-hub',   d: 'M335 180 C354 185 370 185 410 205', tone: 'violet', opacity: 0.42 },
  { id: 'current-task-to-left-hub',     d: 'M335 206 C356 205 372 211 410 205', tone: 'violet', opacity: 0.46 },
  { id: 'active-files-to-left-hub',     d: 'M335 230 C358 230 374 222 410 205', tone: 'violet', opacity: 0.36 },
  { id: 'vision-develop-to-left-hub',   d: 'M235 345 C286 306 347 246 410 205', tone: 'pink',   opacity: 0.5  },

  // CENTRAL APP SYSTEM
  { id: 'left-hub-to-vscode',           d: 'M410 205 C422 185 436 173 462 170', tone: 'violet', opacity: 0.44 },
  { id: 'left-hub-to-slack',            d: 'M410 205 C426 213 441 218 463 219', tone: 'pink',   opacity: 0.44 },
  { id: 'left-hub-to-bridge',           d: 'M410 205 C436 196 459 190 458 195', tone: 'violet', opacity: 0.32 },
  { id: 'vscode-to-figma',              d: 'M462 170 C472 154 485 146 502 150', tone: 'pink',   opacity: 0.42 },
  { id: 'figma-to-browser',             d: 'M502 150 C520 146 536 154 543 169', tone: 'cyan',   opacity: 0.42 },
  { id: 'vscode-to-slack',              d: 'M462 170 C456 187 456 203 463 219', tone: 'violet', opacity: 0.34 },
  { id: 'slack-to-calendar',            d: 'M463 219 C476 222 490 222 504 217', tone: 'pink',   opacity: 0.52 },
  { id: 'figma-to-calendar',            d: 'M502 150 C504 176 505 197 504 217', tone: 'violet', opacity: 0.54 },
  { id: 'calendar-to-notion',           d: 'M504 217 C517 221 532 221 544 219', tone: 'cyan',   opacity: 0.46 },
  { id: 'calendar-to-understanding',    d: 'M504 217 C504 250 502 285 500 318', tone: 'cyan',   opacity: 0.58 },

  // MEMORY SYSTEM
  { id: 'understanding-to-memory',      d: 'M500 286 C500 300 500 313 500 326', tone: 'memory', opacity: 0.34, width: 0.42 },
  { id: 'memory-to-lower-region',       d: 'M500 326 C500 350 500 378 500 405', tone: 'memory', opacity: 0.32, width: 0.4  },
  { id: 'top-to-user-memory',           d: 'M498 318 C473 336 446 354 422 374', tone: 'memory', opacity: 0.3,  width: 0.4  },
  { id: 'top-to-context-memory',        d: 'M498 318 C526 337 554 355 581 374', tone: 'memory', opacity: 0.3,  width: 0.4  },
  { id: 'project-memory-to-command',    d: 'M500 405 C499 430 499 455 500 438', tone: 'memory', opacity: 0.48, width: 0.44 },

  // RIGHT AUTOMATION SYSTEM
  { id: 'browser-to-execute-terminal',  d: 'M559 169 C598 158 657 158 689 163', tone: 'gold',   opacity: 0.54 },
  { id: 'browser-to-actions-control',   d: 'M559 169 C608 215 648 282 695 300', tone: 'gold',   opacity: 0.42 },
  { id: 'browser-to-proactive',         d: 'M559 169 C666 274 787 350 880 391', tone: 'gold',   opacity: 0.34 },

  // TERMINAL WORKFLOW
  { id: 'download-to-analyze',          d: 'M795 255 C813 255 828 255 844 255', tone: 'cyan',   opacity: 0.48 },
  { id: 'analyze-to-send-email',        d: 'M844 255 C862 255 877 255 893 255', tone: 'violet', opacity: 0.48 },
  { id: 'workflow-return-bracket',      d: 'M862 252 C849 295 807 292 780 250', tone: 'pink',   opacity: 0.28 },

  // MULTI-AGENT SYSTEM
  { id: 'memory-context-to-researcher', d: 'M559 169 C704 372 647 378 665 381', tone: 'agent',  opacity: 0.4  },
  { id: 'researcher-to-coder',          d: 'M665 381 C680 366 698 358 715 360', tone: 'agent',  opacity: 0.36 },
  { id: 'researcher-to-agent-grid',     d: 'M665 381 C681 385 697 396 709 408', tone: 'agent',  opacity: 0.36 },
  { id: 'coder-to-agent-grid',          d: 'M715 360 C718 378 715 394 709 408', tone: 'agent',  opacity: 0.32 },
  { id: 'designer-to-agent-grid',       d: 'M761 382 C743 386 724 397 709 408', tone: 'agent',  opacity: 0.32 },
  { id: 'planner-to-agent-grid',        d: 'M671 438 C685 429 699 419 709 408', tone: 'agent',  opacity: 0.34 },
  { id: 'automator-to-agent-grid',      d: 'M757 438 C742 428 724 417 709 408', tone: 'agent',  opacity: 0.32 },
  { id: 'planner-to-automator-arc',     d: 'M671 438 C690 466 733 466 757 438', tone: 'agent',  opacity: 0.3  },

  // PROACTIVE SYSTEM
  { id: 'proactive-card-grouping',      d: 'M880 391 C892 382 903 385 910 398', tone: 'pink',   opacity: 0.22 },
]

const dots = [
  { x: 267, y: 132, r: 3,    opacity: 0.98 },
  { x: 338, y: 180, r: 2.1,  opacity: 0.85 },
  { x: 337, y: 206, r: 2.1,  opacity: 0.85 },
  { x: 338, y: 230, r: 2.1,  opacity: 0.82 },
  { x: 236, y: 345, r: 2.7,  opacity: 0.94 },
  { x: 410, y: 205, r: 3.9,  opacity: 1    },
  { x: 462, y: 170, r: 2.05, opacity: 0.78 },
  { x: 502, y: 150, r: 2.2,  opacity: 0.82 },
  { x: 543, y: 169, r: 2.05, opacity: 0.78 },
  { x: 463, y: 219, r: 2.05, opacity: 0.76 },
  { x: 504, y: 217, r: 2.85, opacity: 0.96 },
  { x: 544, y: 219, r: 2,    opacity: 0.76 },
  { x: 458, y: 195, r: 2,    opacity: 0.74 },
  { x: 502, y: 276, r: 2.15, opacity: 0.74 },
  { x: 500, y: 318, r: 2.6,  opacity: 0.86 },
  { x: 500, y: 340, r: 2.35, opacity: 0.84 },
  { x: 422, y: 374, r: 2.35, opacity: 0.84 },
  { x: 500, y: 374, r: 2.35, opacity: 0.84 },
  { x: 581, y: 374, r: 2.35, opacity: 0.84 },
  { x: 500, y: 399, r: 2.65, opacity: 0.88 },
  { x: 500, y: 438, r: 2.35, opacity: 0.96 },
  { x: 559, y: 169, r: 3,    opacity: 0.94 },
  { x: 689, y: 163, r: 3.1,  opacity: 0.96 },
  { x: 695, y: 300, r: 2.9,  opacity: 0.93 },
  { x: 880, y: 391, r: 3,    opacity: 0.95 },
  { x: 780, y: 250, r: 2.1,  opacity: 0.78 },
  { x: 862, y: 252, r: 2.1,  opacity: 0.78 },
  { x: 668, y: 381, r: 2.2,  opacity: 0.8  },
  { x: 715, y: 360, r: 2.2,  opacity: 0.8  },
  { x: 709, y: 408, r: 2.9,  opacity: 0.92 },
  { x: 761, y: 382, r: 2.1,  opacity: 0.78 },
  { x: 671, y: 438, r: 2.1,  opacity: 0.78 },
  { x: 757, y: 438, r: 2.1,  opacity: 0.78 },
]

// Tone → particle colour + trail colour
const PARTICLE_COLORS = {
  violet: { head: '#e0c8ff', trail: '#a87bff' },
  cyan:   { head: '#c8f6ff', trail: '#3ed8ff' },
  pink:   { head: '#ffd6f0', trail: '#f080d0' },
  gold:   { head: '#fff0c0', trail: '#ffcc55' },
  memory: { head: '#e8d8ff', trail: '#c07bff' },
  agent:  { head: '#c0f0ff', trail: '#5fd8ff' },
}

// How many particles per wire (busier wires get more)
function particleCount(path) {
  const busyPaths = ['browser-to-proactive', 'memory-context-to-researcher', 'browser-to-actions-control']
  return busyPaths.includes(path.id) ? 3 : 2
}

// Speed tiers — slower feel
const SPEED_BASE = {
  'prompt-cloud-to-left-hub':      5.5,
  'browser-to-proactive':          9.0,
  'memory-context-to-researcher':  7.5,
  'browser-to-execute-terminal':   5.0,
  'calendar-to-understanding':     4.8,
}

export function ConnectorLayer() {
  const revealed = useReveal()
  return (
    <svg
      className="pointer-events-none absolute inset-0 z-10 h-full w-full"
      viewBox="0 0 1000 560"
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <defs>
        {/* Line gradients */}
        <linearGradient id="lineGlowViolet" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0"    stopColor="#ffb3d9" stopOpacity="0.8" />
          <stop offset="0.48" stopColor="#c07bff" stopOpacity="0.7" />
          <stop offset="1"    stopColor="#69d7ff" stopOpacity="0.75" />
        </linearGradient>
        <linearGradient id="lineGlowCyan" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stopColor="#9f7cff" stopOpacity="0.65" />
          <stop offset="1" stopColor="#65e7ff" stopOpacity="0.85" />
        </linearGradient>
        <linearGradient id="lineGlowPink" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0"    stopColor="#ffd0b5" stopOpacity="0.72" />
          <stop offset="0.55" stopColor="#f58bff" stopOpacity="0.68" />
          <stop offset="1"    stopColor="#b68bff" stopOpacity="0.6" />
        </linearGradient>
        <linearGradient id="lineGlowGold" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0"   stopColor="#67dcff" stopOpacity="0.72" />
          <stop offset="0.5" stopColor="#7aa7ff" stopOpacity="0.58" />
          <stop offset="1"   stopColor="#ffd49a" stopOpacity="0.82" />
        </linearGradient>
        <linearGradient id="lineGlowMemory" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0"    stopColor="#a884ff" stopOpacity="0.58" />
          <stop offset="0.62" stopColor="#d9c4ff" stopOpacity="0.52" />
          <stop offset="1"    stopColor="#fff3cf" stopOpacity="0.76" />
        </linearGradient>
        <linearGradient id="lineGlowAgent" x1="0" x2="1" y1="0" y2="1">
          <stop offset="0"    stopColor="#5fd8ff" stopOpacity="0.62" />
          <stop offset="0.52" stopColor="#8e83ff" stopOpacity="0.52" />
          <stop offset="1"    stopColor="#c77dff" stopOpacity="0.6" />
        </linearGradient>

        {/* Glow filters */}
        <filter id="softGlow" x="-140%" y="-140%" width="380%" height="380%" filterUnits="objectBoundingBox">
          <feGaussianBlur stdDeviation="3" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
        <filter id="nodeGlow" x="-200%" y="-200%" width="500%" height="500%" filterUnits="objectBoundingBox">
          <feGaussianBlur stdDeviation="4" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
        <filter id="particleGlow" x="-300%" y="-300%" width="700%" height="700%" filterUnits="objectBoundingBox">
          <feGaussianBlur stdDeviation="2.5" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>

        {/* Dot gradients */}
        <radialGradient id="dotGradMain" cx="35%" cy="35%" r="65%">
          <stop offset="0%"   stopColor="#fff9e6" stopOpacity="1" />
          <stop offset="60%"  stopColor="#ffe4a0" stopOpacity="0.9" />
          <stop offset="100%" stopColor="#ffb840" stopOpacity="0.7" />
        </radialGradient>
        <radialGradient id="dotGradHub" cx="35%" cy="35%" r="65%">
          <stop offset="0%"   stopColor="#ffffff" stopOpacity="1" />
          <stop offset="50%"  stopColor="#c8f0ff" stopOpacity="0.95" />
          <stop offset="100%" stopColor="#7ad4ff" stopOpacity="0.8" />
        </radialGradient>

        {/* Hidden paths for animateMotion reference */}
        {paths.map(p => (
          <path key={`ref-${p.id}`} id={`ref-${p.id}`} d={p.d} />
        ))}
      </defs>

      {/* ── Wire paths ─────────────────────────────────────────────────────── */}
      {paths.map((path, i) => {
        const toneKey = path.tone === 'cyan'   ? 'Cyan'
                      : path.tone === 'pink'   ? 'Pink'
                      : path.tone === 'gold'   ? 'Gold'
                      : path.tone === 'memory' ? 'Memory'
                      : path.tone === 'agent'  ? 'Agent'
                      : 'Violet'
        return (
          <path
            key={path.id}
            d={path.d}
            fill="none"
            stroke={`url(#lineGlow${toneKey})`}
            strokeLinecap="round"
            strokeWidth={path.width ?? 0.52}
            filter="url(#softGlow)"
            pathLength="1"
            strokeDasharray="1"
            strokeDashoffset={revealed ? 0 : 1}
            style={{
              opacity:    path.opacity,
              transition: `stroke-dashoffset 1.4s ease ${1100 + i * 28}ms`,
            }}
          />
        )
      })}

      {/* ── Energy pulse sweeps (stroke-dashoffset) ─────────────────────────── */}
      {paths.map((path) => {
        const clr   = PARTICLE_COLORS[path.tone] ?? PARTICLE_COLORS.violet
        const count = particleCount(path)
        const speed = SPEED_BASE[path.id] ?? (2.0 + Math.abs(path.id.charCodeAt(0) - 97) * 0.09)
        const pathLen = 300   // virtual length for dasharray math

        return Array.from({ length: count }, (_, pi) => {
          const offset   = ((pi / count) * speed).toFixed(2)
          const dur      = speed.toFixed(2) + 's'
          const dashLen  = 8    // smaller pulse segment
          const gapLen   = pathLen - dashLen
          const pKey     = `${path.id}-pulse${pi}`

          return (
            <g key={pKey}>
              {/* Wide soft halo */}
              <path
                d={path.d}
                fill="none"
                stroke={clr.trail}
                strokeLinecap="round"
                strokeWidth={2.0}
                strokeDasharray={`${dashLen * 0.65} ${gapLen}`}
                opacity="0"
                filter="url(#particleGlow)"
              >
                <animate attributeName="stroke-dashoffset"
                  from={pathLen} to={-dashLen}
                  dur={dur} begin={`-${offset}s`} repeatCount="indefinite" />
                <animate attributeName="opacity"
                  values="0;0.38;0.35;0.38;0"
                  keyTimes="0;0.04;0.5;0.96;1"
                  dur={dur} begin={`-${offset}s`} repeatCount="indefinite" />
              </path>

              {/* Bright core pulse */}
              <path
                d={path.d}
                fill="none"
                stroke={clr.head}
                strokeLinecap="round"
                strokeWidth={0.9}
                strokeDasharray={`${dashLen} ${gapLen}`}
                opacity="0"
              >
                <animate attributeName="stroke-dashoffset"
                  from={pathLen} to={-dashLen}
                  dur={dur} begin={`-${offset}s`} repeatCount="indefinite" />
                <animate attributeName="opacity"
                  values="0;0.92;0.88;0.92;0"
                  keyTimes="0;0.04;0.5;0.96;1"
                  dur={dur} begin={`-${offset}s`} repeatCount="indefinite" />
              </path>
            </g>
          )
        })
      })}

      {/* ── Junction dots ──────────────────────────────────────────────────── */}
      {dots.map((dot, i) => {
        const isHub     = dot.r >= 3.5
        const grad      = isHub ? 'url(#dotGradHub)' : 'url(#dotGradMain)'
        const pulseR    = dot.r * (isHub ? 2.6 : 2.2)
        const pulseDur  = (2.2 + (i % 5) * 0.4).toFixed(1) + 's'
        const pulseDelay= ((i % 7) * 0.35).toFixed(1) + 's'
        const dotDelay  = 1150 + i * 18
        return (
          <g key={`${dot.x}-${dot.y}`}
            style={{ opacity: revealed ? 1 : 0, transition: `opacity 0.5s ease ${dotDelay}ms` }}
          >
            <circle cx={dot.x} cy={dot.y} r={pulseR} fill="none"
              stroke={isHub ? '#7ad4ff' : '#ffe4b7'} strokeWidth="0.6"
              opacity="0" filter="url(#softGlow)"
            >
              <animate attributeName="r" values={`${dot.r};${pulseR * 1.4}`} dur={pulseDur} begin={pulseDelay} repeatCount="indefinite" />
              <animate attributeName="opacity" values="0.55;0" dur={pulseDur} begin={pulseDelay} repeatCount="indefinite" />
            </circle>
            <circle cx={dot.x} cy={dot.y} r={dot.r} fill={grad} opacity={dot.opacity} filter="url(#nodeGlow)" />
          </g>
        )
      })}

      {/* ── Connector labels ───────────────────────────────────────────────── */}
      {connectorLabels.map((item) => (
        <text
          key={item.label}
          x={item.x * 10}
          y={item.y * 5.6}
          transform={`rotate(${item.rotate} ${item.x * 10} ${item.y * 5.6})`}
          fill="rgba(255,255,255,0.48)"
          fontSize="4.8"
          fontWeight="600"
        >
          {item.label}
        </text>
      ))}
    </svg>
  )
}
