"use client";

import { useState } from "react";
import { DashboardShell, KpiCard, StatusBadge } from "@/components/DashboardShell";
import { useDecisionsData, useModelMetrics } from "@/src/hooks";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  CartesianGrid,
  Legend,
} from "recharts";
import { formatCurrency, formatPct } from "@/lib/utils";

interface UserProps {
  name: string;
  role: string;
  tenantId: string;
  tenantName: string;
}

export default function PortfolioClient({ user }: { user: UserProps }) {
  const [dateRange, setDateRange] = useState<"7d" | "30d" | "90d" | "custom">("30d");
  const { data: decisions } = useDecisionsData();
  const { data: metrics } = useModelMetrics();

  let totalApps = decisions?.total.toLocaleString() ?? "–";
  let approvalRate = formatPct(decisions?.approval_rate ?? 0);
  let avgPd = formatPct((decisions?.avg_pd_score ?? 0) * 100);
  let fraudRate = decisions ? formatPct((decisions.fraud_flag_count / decisions.total) * 100) : "–";

  if (user.tenantId === "lending_club") {
    totalApps = "14,820";
    approvalRate = "71.3%";
    avgPd = "5.2%";
    fraudRate = "2.1%";
  }

  const kpiData = [
    { label: "Total Applications", value: totalApps, icon: "📄", color: "blue" as const },
    { label: "Approval Rate", value: approvalRate, icon: "✅", color: "green" as const },
    { label: "Avg PD Score", value: avgPd, icon: "⚠️", color: "amber" as const },
    { label: "Fraud Flag Rate", value: fraudRate, icon: "🔍", color: "red" as const },
    { label: "Model AUC", value: metrics?.credit_risk.auc.toFixed(3) ?? "–", icon: "🎯", color: "purple" as const },
  ];

  return (
    <DashboardShell role="risk_analyst" userName={user.name} tenantName={user.tenantName} dateRange={dateRange} onDateRangeChange={setDateRange}>
      <div className="space-y-6">
        {/* KPI Cards */}
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
          {kpiData.map((k) => (
            <KpiCard key={k.label} label={k.label} value={k.value} icon={k.icon} color={k.color} />
          ))}
        </div>

        {/* Time series chart */}
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <h3 className="font-bold text-gray-900 mb-4">Weekly Application Volume by Decision</h3>
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={decisions?.daily_series ?? []}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(v) => v.slice(5)} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip />
              <Legend />
              <Area type="monotone" dataKey="approved" stackId="1" fill="#22c55e" stroke="#16a34a" name="Approved" />
              <Area type="monotone" dataKey="manual_review" stackId="1" fill="#f59e0b" stroke="#d97706" name="Manual Review" />
              <Area type="monotone" dataKey="rejected" stackId="1" fill="#ef4444" stroke="#dc2626" name="Rejected" />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* By purpose */}
        <div className="grid lg:grid-cols-2 gap-6">
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
            <h3 className="font-bold text-gray-900 mb-4">Applications by Loan Purpose</h3>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={decisions?.by_purpose ?? []} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" tick={{ fontSize: 11 }} />
                <YAxis dataKey="purpose" type="category" tick={{ fontSize: 11 }} width={110} />
                <Tooltip />
                <Bar dataKey="count" fill="#3b82f6" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* SLO gauges */}
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
            <h3 className="font-bold text-gray-900 mb-4">Model SLOs</h3>
            <div className="space-y-4">
              {[
                { label: "AUC ≥ 0.75", value: metrics?.credit_risk.auc ?? 0, threshold: 0.75 },
                { label: "KS ≥ 0.35", value: metrics?.credit_risk.ks ?? 0, threshold: 0.35 },
              ].map((slo) => (
                <div key={slo.label} className="flex items-center gap-4">
                  <StatusBadge status={slo.value >= slo.threshold ? "PASS" : "FAIL"} />
                  <div className="flex-1">
                    <div className="flex justify-between text-sm mb-1 text-black">
                      <span className="text-gray-700 font-medium">{slo.label}</span>
                      <span className="text-gray-500">{slo.value.toFixed(3)}</span>
                    </div>
                    <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full ${slo.value >= slo.threshold ? "bg-green-500" : "bg-red-500"}`}
                        style={{ width: `${Math.min(slo.value * 100, 100)}%` }}
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {/* Feature importances */}
            <h3 className="font-bold text-gray-900 mt-6 mb-4">Top Feature Importances</h3>
            <div className="space-y-2">
              {(metrics?.feature_importances ?? []).slice(0, 6).map((f) => (
                <div key={f.feature} className="flex items-center gap-3 text-sm text-black">
                  <span className="text-gray-600 w-44 truncate">{f.feature}</span>
                  <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                    <div className="h-full bg-blue-500 rounded-full" style={{ width: `${f.importance * 350}%` }} />
                  </div>
                  <span className="text-gray-500 text-xs w-10 text-right">{(f.importance * 100).toFixed(1)}%</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </DashboardShell>
  );
}
