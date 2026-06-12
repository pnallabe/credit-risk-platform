"use client";

import { useSearchParams } from 'next/navigation';
import { Suspense } from 'react';
import Sidebar from './Sidebar';
import Header from './Header';

function AppShellContent({ children }: { children: React.ReactNode }) {
  const searchParams = useSearchParams();
  const isEmbed = searchParams.get('embed') === 'true';

  // Get pathname safely for SSR
  const pathname = typeof window !== 'undefined' ? window.location.pathname : '';
  const isLoginRoute = pathname === '/login';
  const isTenantSelection = pathname === '/select-tenant';

  if (isEmbed || isLoginRoute || isTenantSelection) {
    return (
      <div className="embed-container" style={{ minHeight: '100vh', backgroundColor: 'var(--bg-main)' }}>
        <div className="page-content" style={{ padding: isLoginRoute ? 0 : '1.5rem' }}>{children}</div>
      </div>
    );
  }

  return (
    <div className="app-container">
      <Sidebar />
      <main className="main-content">
        <Header />
        <div className="page-content">{children}</div>
      </main>
    </div>
  );
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={
      <div className="app-container">
        <Sidebar />
        <main className="main-content">
          <Header />
          <div className="page-content">{children}</div>
        </main>
      </div>
    }>
      <AppShellContent>{children}</AppShellContent>
    </Suspense>
  );
}
