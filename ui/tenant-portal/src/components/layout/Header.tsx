"use client";
import { Bell, Search, Moon, Sun, LogOut } from 'lucide-react';
import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';

export default function Header() {
  const [theme, setTheme] = useState('dark');
  const [tenantSlug, setTenantSlug] = useState('');
  const router = useRouter();

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    setTenantSlug(localStorage.getItem('helix_tenant_slug') || '');
  }, [theme]);

  const toggleTheme = () => {
    setTheme(theme === 'light' ? 'dark' : 'light');
  };

  const handleLogout = () => {
    localStorage.removeItem('helix_tenant_token');
    localStorage.removeItem('helix_tenant_id');
    localStorage.removeItem('helix_tenant_slug');
    localStorage.removeItem('helix_tenants');
    // Clear the HTTP-only cookie by expiring it via a server call
    fetch('/api/auth/logout', { method: 'POST' }).catch(() => null);
    router.push('/login');
  };

  return (
    <header className="header">
      <div style={{ position: 'relative', width: '300px' }}>
        <Search size={18} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-tertiary)' }} />
        <input
          type="text"
          placeholder="Search portfolios, models..."
          style={{
            width: '100%',
            padding: '0.5rem 1rem 0.5rem 2.5rem',
            borderRadius: 'var(--radius-md)',
            border: '1px solid var(--border-light)',
            backgroundColor: 'var(--bg-main)',
            color: 'var(--text-primary)',
            fontSize: '0.875rem',
            outline: 'none',
            transition: 'border-color 0.2s',
          }}
          onFocus={(e) => (e.target.style.borderColor = 'var(--primary)')}
          onBlur={(e) => (e.target.style.borderColor = 'var(--border-light)')}
        />
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
        {tenantSlug && (
          <span style={{
            fontSize: '0.75rem',
            color: 'var(--text-tertiary)',
            background: 'var(--bg-subtle)',
            borderRadius: 'var(--radius-sm)',
            padding: '0.25rem 0.5rem',
            textTransform: 'capitalize',
          }}>
            {tenantSlug.replace(/-/g, ' ')}
          </span>
        )}

        <button
          onClick={toggleTheme}
          title="Toggle theme"
          style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', justifyContent: 'center', width: '36px', height: '36px', borderRadius: '50%', transition: 'background-color 0.2s', cursor: 'pointer' }}
          onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--bg-subtle)')}
          onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
        >
          {theme === 'light' ? <Moon size={20} /> : <Sun size={20} />}
        </button>

        <button
          title="Notifications"
          style={{ position: 'relative', background: 'none', border: 'none', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', justifyContent: 'center', width: '36px', height: '36px', borderRadius: '50%', transition: 'background-color 0.2s', cursor: 'pointer' }}
          onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--bg-subtle)')}
          onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
        >
          <Bell size={20} />
          <span style={{ position: 'absolute', top: '6px', right: '8px', width: '8px', height: '8px', backgroundColor: 'var(--danger)', borderRadius: '50%', border: '2px solid var(--bg-surface)' }} />
        </button>

        <button
          onClick={handleLogout}
          title="Sign out"
          style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', justifyContent: 'center', width: '36px', height: '36px', borderRadius: '50%', transition: 'background-color 0.2s', cursor: 'pointer' }}
          onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--bg-subtle)')}
          onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
        >
          <LogOut size={20} />
        </button>
      </div>
    </header>
  );
}
