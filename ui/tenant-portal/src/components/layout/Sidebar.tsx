"use client";
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { LayoutDashboard, Activity, PieChart, ShieldCheck, FileText, Settings } from 'lucide-react';
import { canonicalizeTenantSlug } from '@/lib/tenant-routing';

export default function Sidebar() {
  const pathname = usePathname();
  const segments = pathname.split('/').filter(Boolean);
  const tenantSlug = segments[0] === 't' ? canonicalizeTenantSlug(segments[1]) : '';
  const prefixed = (suffix: string) => {
    if (!tenantSlug) return '/select-tenant?reason=missing';
    return `/t/${tenantSlug}${suffix}`;
  };

  const navItems = [
    { name: 'Dashboard', href: prefixed('/dashboard'), icon: LayoutDashboard },
    { name: 'Reports', href: prefixed('/reports'), icon: PieChart },
    { name: 'Model Diagnostics', href: prefixed('/dashboard'), icon: Activity },
    { name: 'Audit & Explainability', href: prefixed('/reports'), icon: FileText },
    { name: 'Compliance', href: prefixed('/reports'), icon: ShieldCheck },
    { name: 'Settings', href: prefixed('/settings'), icon: Settings },
  ];

  return (
    <aside className="sidebar">
      <div style={{ padding: '1.5rem', borderBottom: '1px solid var(--border-light)', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        <div style={{ width: '32px', height: '32px', borderRadius: '8px', background: 'linear-gradient(135deg, var(--primary) 0%, var(--primary-hover) 100%)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'white', fontWeight: 'bold' }}>
          H
        </div>
        <h1 style={{ fontSize: '1.25rem', fontWeight: 700, margin: 0, letterSpacing: '-0.025em' }}>Helix Decisions</h1>
      </div>

      <nav style={{ padding: '1rem 0.5rem', display: 'flex', flexDirection: 'column', gap: '0.25rem', flex: 1 }}>
        {navItems.map((item) => (
          <Link
            key={item.name}
            href={item.href}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.75rem',
              padding: '0.75rem 1rem',
              borderRadius: 'var(--radius-md)',
              color: 'var(--text-secondary)',
              fontWeight: 500,
              transition: 'all 0.2s ease',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--bg-subtle)';
              e.currentTarget.style.color = 'var(--primary)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent';
              e.currentTarget.style.color = 'var(--text-secondary)';
            }}
          >
            <item.icon size={20} />
            {item.name}
          </Link>
        ))}
      </nav>

      <div style={{ padding: '1.5rem', borderTop: '1px solid var(--border-light)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <div style={{ width: '36px', height: '36px', borderRadius: '50%', backgroundColor: 'var(--primary-light)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--primary)', fontWeight: 600 }}>
            AC
          </div>
          <div>
            <div style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--text-primary)' }}>Acme Corp</div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)' }}>Tenant ID: t_8921a</div>
          </div>
        </div>
      </div>
    </aside>
  );
}
