import './Navbar.css'

const NAV_LINKS = ['Home', 'Features', 'Memory', 'Automations', 'Ecosystem', 'Roadmap']

export default function Navbar({ progress }) {
  const opacity     = progress
  const translateY  = `${(1 - progress) * -100}%`

  return (
    <>
      {/* ── Hidden SVG filter — liquid glass distortion ─────────────────── */}
      <svg style={{ display: 'none' }} aria-hidden="true">
        <defs>
          <filter
            id="navbar-glass-distortion"
            x="0%" y="0%"
            width="100%" height="100%"
            filterUnits="objectBoundingBox"
          >
            <feTurbulence
              type="fractalNoise"
              baseFrequency="0.01 0.01"
              numOctaves="1"
              seed="5"
              result="turbulence"
            />
            <feComponentTransfer in="turbulence" result="mapped">
              <feFuncR type="gamma" amplitude="1"  exponent="10" offset="0.5" />
              <feFuncG type="gamma" amplitude="0"  exponent="1"  offset="0"   />
              <feFuncB type="gamma" amplitude="0"  exponent="1"  offset="0.5" />
            </feComponentTransfer>
            <feGaussianBlur in="turbulence" stdDeviation="3" result="softMap" />
            <feSpecularLighting
              in="softMap"
              surfaceScale="5"
              specularConstant="1"
              specularExponent="100"
              lightingColor="white"
              result="specLight"
            >
              <fePointLight x="-200" y="-200" z="300" />
            </feSpecularLighting>
            <feComposite
              in="specLight"
              operator="arithmetic"
              k1="0" k2="1" k3="1" k4="0"
              result="litImage"
            />
            <feDisplacementMap
              in="SourceGraphic"
              in2="softMap"
              scale="150"
              xChannelSelector="R"
              yChannelSelector="G"
            />
          </filter>
        </defs>
      </svg>

      {/* ── Navbar ───────────────────────────────────────────────────────── */}
      <nav
        className="navbar"
        style={{ opacity, transform: `translateX(-50%) translateY(${translateY})` }}
        aria-hidden={progress < 0.05}
      >
        {/* liquidGlass-wrapper → navbar-inner pill */}
        <div className="navbar-inner">

          {/* Layer 0 — SVG glass distortion blur */}
          <div className="navbar-glass-effect" aria-hidden="true" />

          {/* Layer 1 — tri-mode colour tint */}
          <div className="navbar-glass-tint" aria-hidden="true" />

          {/* Layer 2 — inset shine + animated shimmer sweep */}
          <div className="navbar-glass-shine" aria-hidden="true" />

          {/* Layer 3 — actual content */}
          <div className="navbar-content">

            {/* Logo */}
            <div className="navbar-logo">
              <span className="logo-star">✦</span>
              <span className="logo-text">VYRA</span>
            </div>

            {/* Nav links */}
            <ul className="navbar-links">
              {NAV_LINKS.map((link, i) => (
                <li key={link} className={i === 0 ? 'nav-item active' : 'nav-item'}>
                  <a href={`#${link.toLowerCase()}`}>{link}</a>
                  {i === 0 && <span className="active-dot" />}
                </li>
              ))}
            </ul>

            {/* CTA */}
            <button className="navbar-cta">
              Join Waitlist <span className="cta-arrow">→</span>
            </button>

          </div>
        </div>
      </nav>
    </>
  )
}
