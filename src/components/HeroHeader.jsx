import { useReveal } from './RevealContext'

export function HeroHeader() {
  const revealed = useReveal()
  return (
    <header
      className="absolute left-0 top-[6%] z-20 flex w-full flex-col items-center justify-center text-center"
      style={{
        opacity: revealed ? 1 : 0,
        transform: revealed ? 'translateY(0)' : 'translateY(-14px)',
        transition: 'opacity 0.7s ease 80ms, transform 0.7s ease 80ms',
      }}
    >
      <p className="font-medium uppercase tracking-widest text-[#a87bff] [font-size:clamp(10px,0.85cqw,14px)]">
        The Vyra Ecosystem
      </p>
      <h1 className="mt-4 font-bold leading-[1.05] text-[#f5f5fb] drop-shadow-[0_2px_12px_rgba(255,255,255,0.2)] [font-size:clamp(28px,3cqw,46px)]">
        A Seamless Intelligence Layer
      </h1>
      <p className="mt-4 max-w-2xl font-medium leading-relaxed text-white/58 [font-size:clamp(14px,1.2cqw,18px)]">
        Everything you do, seamlessly understood.
      </p>
    </header>
  )
}
