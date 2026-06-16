import { useReveal } from './RevealContext'

export function SectionLabel({ title, children, className = '', align = 'left', delay = 800, direction = 'up' }) {
  const revealed = useReveal()

  const fromX = direction === 'left' ? '-10px' : direction === 'right' ? '10px' : '0'
  const fromY = direction === 'up' ? '12px' : '0'

  return (
    <div
      className={`absolute z-20 ${align === 'center' ? 'text-center' : 'text-left'} ${className}`}
      style={{
        opacity:    revealed ? 1 : 0,
        transform:  revealed
          ? 'translate(0, 0)'
          : `translate(${fromX}, ${fromY})`,
        transition: `opacity 0.7s ease ${delay}ms, transform 0.7s ease ${delay}ms`,
        willChange: 'transform, opacity',
      }}
    >
      <h2 className="font-semibold leading-tight text-[#f4f4f8]/95 [font-size:clamp(12px,1.32cqw,20px)]">
        {title}
      </h2>
      {children && (
        <p className="mt-1 font-normal leading-[1.14] text-white/62 [font-size:clamp(7px,0.66cqw,10px)]">
          {children}
        </p>
      )}
    </div>
  )
}
