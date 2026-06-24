"use client";

import Link from 'next/link';
import {
  Activity,
  Briefcase,
  ShieldCheck,
  FileText,
  BarChart3,
  Users,
  Lock,
  LineChart
} from 'lucide-react';

export default function PortalHub() {
  const nativeDashboards = [
    { name: 'Model Diagnostics', href: '/model-diagnostics', icon: <Activity size={24} />, desc: 'Real-time performance metrics and explainability' },
    { name: 'Portfolio Analysis', href: '/portfolio', icon: <Briefcase size={24} />, desc: 'Concentration risk and distribution analysis' },
    { name: 'Compliance', href: '/compliance', icon: <ShieldCheck size={24} />, desc: 'Fair lending and bias monitoring' },
    { name: 'Audit Logs', href: '/audit', icon: <FileText size={24} />, desc: 'Comprehensive decision logs and records' },
  ];

  const analyticsUrl = process.env.NEXT_PUBLIC_ANALYTICS_PORTAL_URL || 'http://localhost:3001';

  const analyticsDashboards = [
    { name: 'Executive Overview', href: analyticsUrl, icon: <BarChart3 size={24} />, desc: 'High-level portfolio and financial metrics' },
    { name: 'Underwriter Queue', href: analyticsUrl, icon: <Users size={24} />, desc: 'Manual review and application processing' },
    { name: 'Risk Analyst View', href: analyticsUrl, icon: <LineChart size={24} />, desc: 'Vintage curves and cohort analysis' },
    { name: 'Data Scientist Space', href: analyticsUrl, icon: <Lock size={24} />, desc: 'Model drift and feature importance deep dives' },
  ];

  return (
    <div className="flex flex-col gap-6 p-4">
      <div>
        <h1 style={{ fontSize: '2rem', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '0.5rem' }}>
          Helix Decisions Hub
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: '1.1rem' }}>
          Select a workspace to manage your credit risk operations.
        </p>
      </div>

      <div style={{ marginTop: '2rem' }}>
        <h2 style={{ fontSize: '1.25rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '1.25rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{ width: '8px', height: '24px', background: 'var(--primary)', borderRadius: '4px' }}></span>
          Native Workspaces
        </h2>
        <div className="grid grid-cols-4" style={{ gap: '1.5rem' }}>
          {nativeDashboards.map((app) => (
            <Link key={app.name} href={app.href} style={{ textDecoration: 'none' }}>
              <div
                className="card"
                style={{
                  height: '100%',
                  transition: 'all 0.2s',
                  cursor: 'pointer',
                  border: '1px solid var(--border-light)',
                  padding: '1.5rem'
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = 'var(--primary)';
                  e.currentTarget.style.transform = 'translateY(-4px)';
                  e.currentTarget.style.boxShadow = '0 12px 24px rgba(0,0,0,0.2)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = 'var(--border-light)';
                  e.currentTarget.style.transform = 'translateY(0)';
                  e.currentTarget.style.boxShadow = 'none';
                }}
              >
                <div style={{
                  width: '48px',
                  height: '48px',
                  borderRadius: '12px',
                  background: 'rgba(59, 130, 246, 0.1)',
                  color: 'var(--primary)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  marginBottom: '1rem'
                }}>
                  {app.icon}
                </div>
                <h3 style={{ fontSize: '1.1rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.5rem' }}>
                  {app.name}
                </h3>
                <p style={{ fontSize: '0.9rem', color: 'var(--text-tertiary)', lineHeight: '1.5' }}>
                  {app.desc}
                </p>
              </div>
            </Link>
          ))}
        </div>
      </div>

      <div style={{ marginTop: '2.5rem' }}>
        <h2 style={{ fontSize: '1.25rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '1.25rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{ width: '8px', height: '24px', background: 'var(--warning)', borderRadius: '4px' }}></span>
          Analytics Hub (AgentHiveHQ)
        </h2>
        <p style={{ color: 'var(--text-tertiary)', marginBottom: '1.5rem', fontSize: '0.9rem' }}>
          Role-based deep analytical views. These currently open in a separate portal tab while we integrate them.
        </p>
        <div className="grid grid-cols-4" style={{ gap: '1.5rem' }}>
          {analyticsDashboards.map((app) => (
            <a key={app.name} href={app.href} target="_blank" rel="noopener noreferrer" style={{ textDecoration: 'none' }}>
              <div
                className="card"
                style={{
                  height: '100%',
                  transition: 'all 0.2s',
                  cursor: 'pointer',
                  border: '1px solid var(--border-light)',
                  padding: '1.5rem',
                  background: 'rgba(255, 255, 255, 0.01)'
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = 'var(--warning)';
                  e.currentTarget.style.transform = 'translateY(-4px)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = 'var(--border-light)';
                  e.currentTarget.style.transform = 'translateY(0)';
                }}
              >
                <div style={{
                  width: '48px',
                  height: '48px',
                  borderRadius: '12px',
                  background: 'rgba(245, 158, 11, 0.1)',
                  color: 'var(--warning)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  marginBottom: '1rem'
                }}>
                  {app.icon}
                </div>
                <h3 style={{ fontSize: '1.1rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.5rem' }}>
                  {app.name}
                </h3>
                <p style={{ fontSize: '0.9rem', color: 'var(--text-tertiary)', lineHeight: '1.5' }}>
                  {app.desc}
                </p>
              </div>
            </a>
          ))}
        </div>
      </div>
    </div>
  );
}
