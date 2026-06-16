export function GlassPanel({ children, className = '', style }) {
  return (
    <div
      className={`rounded-[8px] border border-white/12 bg-[#151a22]/58 shadow-[inset_0_1px_0_rgba(255,255,255,0.1),0_12px_36px_rgba(0,0,0,0.32)] backdrop-blur-md ${className}`}
      style={style}
    >
      {children}
    </div>
  )
}
