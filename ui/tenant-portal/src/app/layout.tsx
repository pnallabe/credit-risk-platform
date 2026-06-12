import type { Metadata } from 'next';
import './globals.css';
import AppShell from '@/components/layout/AppShell';

export const metadata: Metadata = {
  title: 'Helix Decisions | Tenant Portal',
  description: 'Multi-tenant credit risk intelligence platform',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <AppShell>
          {children}
        </AppShell>
      </body>
    </html>
  );
}
