"use client";
import { useEffect, useState } from 'react';
import { Card, CardHeader } from '@/components/ui/Card';
import { MetricCard } from '@/components/ui/MetricCard';
import { LineChart } from '@/components/charts/LineChart';
import { BarChart } from '@/components/charts/BarChart';
import { fetchMetrics } from '@/lib/api';
import { Activity, Target, Zap, Clock } from 'lucide-react';

const mockMetrics = [
  { date: 'Jan 01', auc: 0.85, ks: 0.42 },
  { date: 'Jan 05', auc: 0.84, ks: 0.40 },
  { date: 'Jan 10', auc: 0.86, ks: 0.44 },
  { date: 'Jan 15', auc: 0.85, ks: 0.43 },
  { date: 'Jan 20', auc: 0.87, ks: 0.45 },
  { date: 'Jan 25', auc: 0.86, ks: 0.46 },
];

const featureImportance = [
  { feature: 'Credit Score', value: 0.35 },
  { feature: 'DTI Ratio', value: 0.25 },
  { feature: 'Loan Term', value: 0.15 },
  { feature: 'Annual Inc', value: 0.10 },
  { feature: 'Emp Length', value: 0.08 },
];

export default function ModelDiagnostics() {
  const [metrics, setMetrics] = useState<any>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadData() {
      try {
        const liveMetrics = await fetchMetrics();
        setMetrics(liveMetrics || {});
      } catch (e) {
        console.error('Failed to load metrics', e);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, []);

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: '0.25rem' }}>Model Diagnostics</h2>
        <p style={{ color: 'var(--text-secondary)' }}>Real-time performance metrics and explainability for your active models.</p>
      </div>

      <div className="grid grid-cols-4">
        <MetricCard
          title="Total Requests"
          value={loading ? "..." : (metrics.total_requests || 0).toLocaleString()}
          icon={<Target size={20} />}
        />
        <MetricCard
          title="Error Rate (5xx)"
          value={loading ? "..." : `${(metrics.error_rate_5xx || 0).toFixed(4)}`}
          icon={<Activity size={20} />}
        />
        <MetricCard
          title="p99 Latency"
          value={loading ? "..." : `${metrics.p99_latency_ms || 0}ms`}
          icon={<Clock size={20} />}
        />
        <MetricCard
          title="Canary Health"
          value={loading ? "..." : (metrics.canary_healthy === false ? "Degraded" : "Healthy")}
          icon={<Zap size={20} />}
        />
      </div>

      <div className="grid grid-cols-2">
        <Card>
          <CardHeader title="Performance Trend (AUC & KS)" subtitle="Historical model performance over the last 30 days" />
          <LineChart
            data={mockMetrics}
            xKey="date"
            lines={[
              { key: 'auc', color: 'var(--primary)', name: 'AUC' },
              { key: 'ks', color: 'var(--secondary)', name: 'KS Stat' }
            ]}
          />
        </Card>

        <Card>
          <CardHeader title="Feature Importance (SHAP)" subtitle="Top 5 features driving model decisions" />
          <BarChart
            data={featureImportance}
            xKey="feature"
            bars={[
              { key: 'value', color: 'var(--primary)', name: 'Impact Factor' }
            ]}
          />
        </Card>
      </div>
    </div>
  );
}
