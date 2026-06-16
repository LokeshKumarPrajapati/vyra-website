import { useEffect, useRef, useState } from 'react'
import { EcosystemPage } from './EcosystemPage'
import { RevealContext } from './RevealContext'

export function BrowserShell() {
  const [revealed, setRevealed] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    const obs = new IntersectionObserver(
      ([e]) => {
        if (e.isIntersecting) {
          setRevealed(true)
        } else if (e.boundingClientRect.top > 0) {
          // section scrolled back above viewport top — user scrolled up
          setRevealed(false)
        }
      },
      { threshold: 0.1 }
    )
    if (ref.current) obs.observe(ref.current)
    return () => obs.disconnect()
  }, [])

  return (
    <RevealContext.Provider value={revealed}>
      <div ref={ref} className="relative h-screen w-screen overflow-hidden bg-[#07080d]">
        <EcosystemPage />
      </div>
    </RevealContext.Provider>
  )
}
