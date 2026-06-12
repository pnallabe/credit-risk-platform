export function Card({ children, className = '', style = {} }: { children: React.ReactNode; className?: string; style?: React.CSSProperties }) {
  return (
    <div className={`card ${className}`} style={style}>
      {children}
    </div>
  );
}

export function CardHeader({ title, subtitle, action }: { title: string; subtitle?: string; action?: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1.5rem' }}>
      <div>
        <h3 style={{ fontSize: '1.125rem', fontWeight: 600, color: 'var(--text-primary)', margin: 0 }}>{title}</h3>
        {subtitle && <p style={{ fontSize: '0.875rem', color: 'var(--text-tertiary)', marginTop: '0.25rem' }}>{subtitle}</p>}
      </div>
      {action && <div>{action}</div>}
    </div>
  );
}
