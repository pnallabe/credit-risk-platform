"use client";
import { useEffect, useState } from 'react';
import { Card, CardHeader } from '@/components/ui/Card';
import { MetricCard } from '@/components/ui/MetricCard';
import { LineChart } from '@/components/charts/LineChart';
import { BarChart } from '@/components/charts/BarChart';
import { fetchApprovalProfit, fetchVintageCurves } from '@/lib/api';
import { Users, CheckCircle, XCircle, TrendingUp } from 'lucide-react';

export default function PortfolioAnalytics() {
  const [data, setData] = useState<any>({
    volume: [],
    risk: [],
    metrics: { apps: 0, approval: 0, decline: 0, profit: 0 }
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadData() {
      try {
        const [profitRes, vintageRes] = await Promise.all([
          fetchApprovalProfit(),
          fetchVintageCurves()
        ]);

        const profitData = profitRes.data || [];
        const vintageData = vintageRes.data || [];

        // Map live data to UI format
        let totalApps = 0;
        let totalApproved = 0;
        let expectedProfit = 0;
        const mappedVolume = profitData.slice(0, 5).map((d: any) => {
          totalApps += d.total_applications || 0;
          totalApproved += d.approved_count || 0;
          expectedProfit += d.expected_profit_usd || 0;
          return {
            date: d.segment || 'Unknown',
            approved: d.approved_count || 0,
            declined: d.rejected_count || 0,
          };
        });

        const mappedRisk = vintageData.slice(0, 5).map((d: any) => ({
          score: d.bucket || d.origination_month || 'Unknown',
          count: d.cohort_count || 0,
        }));

        setData({
          volume: mappedVolume,
          risk: mappedRisk,
          metrics: {
            apps: totalApps,
            approval: totalApps ? ((totalApproved / totalApps) * 100).toFixed(1) : '0.0',
            decline: totalApps ? (((totalApps - totalApproved) / totalApps) * 100).toFixed(1) : '0.0',
            profit: expectedProfit,
          }
        });
      } catch (e) {
        console.error('Failed to load live data', e);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, []);

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: '0.25rem' }}>Portfolio Analytics</h2>
        <p style={{ color: 'var(--text-secondary)' }}>Analyze loan volumes, approval funnels, and risk distributions.</p>
      </div>

      <div className="grid grid-cols-4">
        <MetricCard
          title="Total Applications"
          value={loading ? "..." : data.metrics.apps.toLocaleString()}
          trend={8.4}
          icon={<Users size={20} />}
        />
        <MetricCard
          title="Approval Rate"
          value={loading ? "..." : `${data.metrics.approval}%`}
          trend={2.1}
          icon={<CheckCircle size={20} />}
        />
        <MetricCard
          title="Decline Rate"
          value={loading ? "..." : `${data.metrics.decline}%`}
          trend={-2.1}
          icon={<XCircle size={20} />}
        />
        <MetricCard
          title="Exp. Profit (USD)"
          value={loading ? "..." : `$${(data.metrics.profit / 1000).toFixed(1)}k`}
          trend={1.4}
          icon={<TrendingUp size={20} />}
        />
      </div>

      <div className="grid grid-cols-2">
        <Card>
          <CardHeader title="Application Volume by Segment" subtitle="Approved vs Declined breakdown" />
          {loading ? <div style={{height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>Loading data...</div> : (
            <BarChart
              data={data.volume}
              xKey="date"
              bars={[
                { key: 'approved', color: 'var(--secondary)', name: 'Approved', stackId: 'a' },
                { key: 'declined', color: 'var(--danger)', name: 'Declined', stackId: 'a' }
              ]}
            />
          )}
        </Card>

        <Card>
          <CardHeader title="Risk Distribution" subtitle="Cohort sizes by risk bucket" />
          {loading ? <div style={{height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>Loading data...</div> : (
            <BarChart
              data={data.risk}
              xKey="score"
              bars={[
                { key: 'count', color: 'var(--primary)', name: 'Loan Count' }
              ]}
            />
          )}
        </Card>
      </div>
    </div>
  );
}
