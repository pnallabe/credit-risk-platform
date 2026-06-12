"use client";
import { useEffect, useState } from 'react';
import { Card, CardHeader } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { fetchPolicyAdherence } from '@/lib/api';
import { Upload, FileText, CheckCircle, AlertTriangle } from 'lucide-react';

export default function ComplianceDashboard() {
  const [adherence, setAdherence] = useState<any>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadData() {
      try {
        const liveData = await fetchPolicyAdherence();
        setAdherence(liveData || {});
      } catch (e) {
        console.error('Failed to load compliance data', e);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, []);

  const documents = [
    { name: 'Model Validation Report_v2.1.pdf', date: '2023-10-15', status: 'Approved' },
    { name: 'Fair Lending Analysis_Q3.pdf', date: '2023-10-01', status: 'Approved' },
    { name: 'ECOA Compliance Checklist.xlsx', date: '2023-11-01', status: 'Pending Review' },
  ];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex justify-between items-center">
        <div>
          <h2 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: '0.25rem' }}>Compliance & Governance</h2>
          <p style={{ color: 'var(--text-secondary)' }}>Manage model documentation, sign-offs, and regulatory compliance artifacts.</p>
        </div>
        <Button icon={<Upload size={16} style={{ marginRight: '0.5rem' }} />}>Upload Document</Button>
      </div>

      <div className="grid grid-cols-2">
        <Card>
          <CardHeader title="Governance Documents" subtitle="Recent uploads and their approval status" />
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {documents.map((doc, i) => (
              <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '1rem', border: '1px solid var(--border-light)', borderRadius: 'var(--radius-md)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                  <div style={{ padding: '0.5rem', backgroundColor: 'var(--bg-subtle)', borderRadius: 'var(--radius-sm)' }}>
                    <FileText size={20} color="var(--primary)" />
                  </div>
                  <div>
                    <div style={{ fontWeight: 500, color: 'var(--text-primary)' }}>{doc.name}</div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)' }}>Uploaded: {doc.date}</div>
                  </div>
                </div>
                <div className={`badge ${doc.status === 'Approved' ? 'badge-success' : ''}`} style={{ backgroundColor: doc.status === 'Pending Review' ? 'var(--primary-light)' : undefined, color: doc.status === 'Pending Review' ? 'var(--primary)' : undefined }}>
                  {doc.status}
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card>
          <CardHeader title="Policy Adherence Metrics" subtitle="Automated checklist status" />
          {loading ? <div style={{padding: '1rem'}}>Loading compliance metrics...</div> : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', paddingBottom: '1rem', borderBottom: '1px solid var(--border-light)' }}>
                {adherence.adherence_rate >= 0.95 ? <CheckCircle size={20} color="var(--secondary)" /> : <AlertTriangle size={20} color="var(--danger)" />}
                <span style={{ fontWeight: 500 }}>Overall Policy Adherence: {adherence.adherence_rate ? (adherence.adherence_rate * 100).toFixed(1) : 100}%</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', paddingBottom: '1rem', borderBottom: '1px solid var(--border-light)' }}>
                <CheckCircle size={20} color="var(--secondary)" />
                <span style={{ fontWeight: 500 }}>Total Approvals: {adherence.total_approvals || 0}</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', paddingBottom: '1rem', borderBottom: 'none' }}>
                <AlertTriangle size={20} color="var(--primary)" />
                <span style={{ fontWeight: 500 }}>Total Exceptions: {adherence.total_exceptions || 0}</span>
              </div>
              <div style={{ marginTop: '1rem' }}>
                <Button variant="outline" style={{ width: '100%' }}>View Full Exception Report</Button>
              </div>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
