import './Navbar.css'

const NAV_LINKS = ['Home', 'Features', 'Memory', 'Automations', 'Ecosystem', 'Roadmap']

export default function Navbar({ progress }) {
  const opacity = progress
  const translateY = `${(1 - progress) * -100}%`

  return (
    <nav
      className="navbar"
      style={{ opacity, transform: `translateX(-50%) translateY(${translateY})` }}
      aria-hidden={progress < 0.05}
    >
      <div className="navbar-inner">
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
          Launch Vyra <span className="cta-arrow">→</span>
        </button>
      </div>
    </nav>
  )
}
