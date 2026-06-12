import { ArrowUpRight, ArrowDownRight } from 'lucide-react';
import { Card } from './Card';

interface MetricCardProps {
  title: string;
  value: string | number;
  trend?: number;
  trendLabel?: string;
  icon?: React.ReactNode;
}

export function MetricCard({ title, value, trend, trendLabel, icon }: MetricCardProps) {
  const isPositive = trend !== undefined && trend > 0;
  const isNegative = trend !== undefined && trend < 0;

  return (
    <Card className="group relative overflow-hidden">
      {/* Subtle background glow based on trend */}
      {trend !== undefined && (
        <div style={{
          position: 'absolute',
          top: '-50%',
          right: '-20%',
          width: '150px',
          height: '150px',
          borderRadius: '50%',
          background: isPositive
            ? 'radial-gradient(circle, rgba(16,185,129,0.1) 0%, transparent 70%)'
            : isNegative
              ? 'radial-gradient(circle, rgba(239,68,68,0.1) 0%, transparent 70%)'
              : 'transparent',
          filter: 'blur(20px)',
          pointerEvents: 'none',
        }} />
      )}

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', position: 'relative', zIndex: 1 }}>
        <div>
          <div className="metric-label">{title}</div>
          <div className="metric-value">{value}</div>
        </div>
        {icon && (
          <div style={{
            width: '44px',
            height: '44px',
            borderRadius: 'var(--radius-md)',
            background: 'linear-gradient(135deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0) 100%)',
            border: '1px solid var(--border-light)',
            color: 'var(--primary)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.1)'
          }}>
            {icon}
          </div>
        )}
      </div>

      {trend !== undefined && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '1.25rem', fontSize: '0.875rem', position: 'relative', zIndex: 1 }}>
          <span style={{
            display: 'inline-flex',
            alignItems: 'center',
            color: isPositive ? 'var(--secondary)' : isNegative ? 'var(--danger)' : 'var(--text-tertiary)',
            fontWeight: 600,
            padding: '0.125rem 0.375rem',
            backgroundColor: isPositive ? 'rgba(16,185,129,0.1)' : isNegative ? 'rgba(239,68,68,0.1)' : 'transparent',
            borderRadius: 'var(--radius-sm)'
          }}>
            {isPositive ? <ArrowUpRight size={14} style={{marginRight: '2px'}}/> : isNegative ? <ArrowDownRight size={14} style={{marginRight: '2px'}}/> : null}
            {Math.abs(trend)}%
          </span>
          <span style={{ color: 'var(--text-tertiary)' }}>{trendLabel || 'vs last month'}</span>
        </div>
      )}
    </Card>
  );
}
