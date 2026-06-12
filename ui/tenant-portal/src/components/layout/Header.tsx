"use client";
import { Bell, Search, Moon, Sun } from 'lucide-react';
import { useState, useEffect } from 'react';

export default function Header() {
  const [theme, setTheme] = useState('light');

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme(theme === 'light' ? 'dark' : 'light');
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
            transition: 'border-color 0.2s'
          }}
          onFocus={(e) => e.target.style.borderColor = 'var(--primary)'}
          onBlur={(e) => e.target.style.borderColor = 'var(--border-light)'}
        />
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
        <button
          onClick={toggleTheme}
          style={{
            background: 'none',
            border: 'none',
            color: 'var(--text-secondary)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: '36px',
            height: '36px',
            borderRadius: '50%',
            transition: 'background-color 0.2s'
          }}
          onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'var(--bg-subtle)'}
          onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
        >
          {theme === 'light' ? <Moon size={20} /> : <Sun size={20} />}
        </button>

        <button
          style={{
            position: 'relative',
            background: 'none',
            border: 'none',
            color: 'var(--text-secondary)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: '36px',
            height: '36px',
            borderRadius: '50%',
            transition: 'background-color 0.2s'
          }}
          onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'var(--bg-subtle)'}
          onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
        >
          <Bell size={20} />
          <span style={{
            position: 'absolute',
            top: '6px',
            right: '8px',
            width: '8px',
            height: '8px',
            backgroundColor: 'var(--danger)',
            borderRadius: '50%',
            border: '2px solid var(--bg-surface)'
          }}></span>
        </button>
      </div>
    </header>
  );
}
