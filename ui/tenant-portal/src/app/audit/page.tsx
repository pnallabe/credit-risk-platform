"use client";
import { useEffect, useState } from 'react';
import { Card, CardHeader } from '@/components/ui/Card';
import { DataTable } from '@/components/ui/DataTable';
import { Button } from '@/components/ui/Button';
import { fetchAuditLogs } from '@/lib/api';
import { Download, Filter } from 'lucide-react';

export default function AuditDashboard() {
  const [logs, setLogs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadData() {
      try {
        const liveLogs = await fetchAuditLogs();
        setLogs(liveLogs.data || []);
      } catch (e) {
        console.error('Failed to load audit logs', e);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, []);

  const columns = [
    { key: 'id', header: 'Audit ID' },
    { key: 'date', header: 'Timestamp' },
    { key: 'user', header: 'User/System' },
    { key: 'action', header: 'Action Taken' },
    { key: 'entity', header: 'Entity Reference' },
    {
      key: 'status',
      header: 'Status',
      render: (item: any) => (
        <span className={`badge ${
          item.status === 'Success' || item.status === 'Approved' ? 'badge-success' :
          item.status === 'Warning' ? 'badge-danger' : ''
        }`} style={{
          backgroundColor: item.status === 'Started' ? 'var(--primary-light)' : undefined,
          color: item.status === 'Started' ? 'var(--primary)' : undefined
        }}>
          {item.status}
        </span>
      )
    },
    {
      key: 'actions',
      header: '',
      render: () => <Button variant="outline" size="sm">View Trail</Button>
    }
  ];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex justify-between items-center">
        <div>
          <h2 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: '0.25rem' }}>Audit & Explainability</h2>
          <p style={{ color: 'var(--text-secondary)' }}>Immutable ledger of decisions, model inferences, and system actions.</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" icon={<Filter size={16} style={{ marginRight: '0.5rem' }} />}>Filter</Button>
          <Button icon={<Download size={16} style={{ marginRight: '0.5rem' }} />}>Export Log</Button>
        </div>
      </div>

      <Card>
        <CardHeader title="Decision Audit Log" subtitle="Showing latest 50 entries" />
        {loading ? <div style={{padding: '1rem'}}>Loading logs...</div> : (
          <DataTable
            data={logs}
            columns={columns}
            keyExtractor={(item) => item.id || Math.random().toString()}
          />
        )}
      </Card>
    </div>
  );
}
