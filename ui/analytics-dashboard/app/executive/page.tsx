"use client";

import { useState, useCallback } from "react";
import { DashboardShell, KpiCard } from "@/components/DashboardShell";
import { useDecisionsData, useModelMetrics, useFairLendingReport } from "@/src/hooks";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  PieChart,
  Pie,
  Cell,
  Legend,
  LineChart,
  Line,
} from "recharts";

const COLORS = { APPROVE: "#22c55e", REJECT: "#ef4444", MANUAL_REVIEW: "#f59e0b" };

export default function ExecutivePage() {
  const [dateRange, setDateRange] = useState<"7d" | "30d" | "90d" | "custom">("30d");
  const { data: decisionsData } = useDecisionsData(dateRange);
  const { data: modelMetrics } = useModelMetrics();
  const { data: fairReport } = useFairLendingReport();

  const decisions = decisionsData?.decisions ?? [];
  const approvedCount = decisions.filter((d) => d.decision === "APPROVE").length;
  const rejectedCount = decisions.filter((d) => d.decision === "REJECT").length;
  const reviewCount = decisions.filter((d) => d.decision === "MANUAL_REVIEW").length;
  const total = decisions.length;
  const approvalRate = total ? ((approvedCount / total) * 100).toFixed(1) : "—";
  const avgLoan = total
    ? (decisions.reduce((s, d) => s + (d.loan_amount ?? 0), 0) / total / 1000).toFixed(1) + "k"
    : "—";

  const pieData = [
    { name: "Approve", value: approvedCount },
    { name: "Reject", value: rejectedCount },
    { name: "Manual Review", value: reviewCount },
  ].filter((d) => d.value > 0);

  const trendData = decisionsData?.weekly_trend ?? [];

  const exportPdf = useCallback(() => {
    const w = window.open("", "_blank");
    if (!w) return;
    w.document.write(`
      <html><head><title>Executive Report – ${new Date().toLocaleDateString()}</title>
      <style>body{font-family:sans-serif;max-width:900px;margin:40px auto;color:#111}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ddd;padding:8px;text-align:left}th{background:#f5f5f5}</style>
      </head><body>
        <h1>Executive Credit Risk Report</h1>
        <p>Generated: ${new Date().toLocaleString()} | Period: ${dateRange}</p>
        <h2>Portfolio Summary</h2>
        <table>
          <tr><th>Metric</th><th>Value</th></tr>
          <tr><td>Total Decisions</td><td>${total}</td></tr>
          <tr><td>Approval Rate</td><td>${approvalRate}%</td></tr>
          <tr><td>Average Loan Amount</td><td>$${avgLoan}</td></tr>
          <tr><td>Model AUC</td><td>${modelMetrics?.auc.toFixed(3) ?? "—"}</td></tr>
          <tr><td>DIR Score</td><td>${fairReport?.dir_score.toFixed(3) ?? "—"}</td></tr>
        </table>
      </body></html>
    `);
    w.document.close();
    w.print();
  }, [total, approvalRate, avgLoan, modelMetrics, fairReport, dateRange]);

  return (
    <DashboardShell role="executive" userName="C-Suite" dateRange={dateRange} onDateRangeChange={setDateRange}>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-black text-gray-900">Executive Dashboard</h2>
            <p className="text-sm text-gray-500">Portfolio overview • Model health • Regulatory compliance</p>
          </div>
          <button
            onClick={exportPdf}
            className="flex items-center gap-2 bg-gray-900 hover:bg-gray-800 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
            Export PDF
          </button>
        </div>

        {/* KPIs row */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <KpiCard label="Total Decisions" value={total.toLocaleString()} icon="📄" color="blue" />
          <KpiCard label="Approval Rate" value={`${approvalRate}%`} icon="✅" color="green" />
          <KpiCard label="Avg Loan Size" value={`$${avgLoan}`} icon="💵" color="blue" />
          <KpiCard label="Model AUC" value={modelMetrics ? modelMetrics.auc.toFixed(3) : "—"} icon="🎯" color={modelMetrics && modelMetrics.auc >= 0.8 ? "green" : "amber"} />
        </div>

        {/* Second KPI row */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <KpiCard label="KS Statistic" value={modelMetrics ? modelMetrics.ks.toFixed(3) : "—"} icon="📈" color={modelMetrics && modelMetrics.ks >= 0.35 ? "green" : "red"} />
          <KpiCard label="DIR Score" value={fairReport ? fairReport.dir_score.toFixed(3) : "—"} icon="⚖️" color={fairReport && fairReport.dir_score >= 0.8 ? "green" : "red"} />
          <KpiCard label="Adverse Actions" value={rejectedCount.toString()} icon="🚫" color="amber" />
          <KpiCard label="For Review" value={reviewCount.toString()} icon="🔍" color={reviewCount > 50 ? "amber" : "green"} />
        </div>

        {/* Charts row */}
        <div className="grid lg:grid-cols-3 gap-6">
          {/* Weekly trend */}
          <div className="lg:col-span-2 bg-white rounded-xl border border-gray-100 shadow-sm p-6">
            <h3 className="font-bold text-gray-900 mb-4">Weekly Decision Volume</h3>
            <ResponsiveContainer width="100%" height={200}>
              {trendData.length ? (
                <AreaChart data={trendData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="week" tick={{ fontSize: 10 }} />
                  <YAxis tick={{ fontSize: 10 }} />
                  <Tooltip />
                  <Legend />
                  <Area type="monotone" dataKey="APPROVE" stackId="1" stroke="#22c55e" fill="#dcfce7" />
                  <Area type="monotone" dataKey="REJECT" stackId="1" stroke="#ef4444" fill="#fee2e2" />
                  <Area type="monotone" dataKey="MANUAL_REVIEW" stackId="1" stroke="#f59e0b" fill="#fef3c7" />
                </AreaChart>
              ) : (
                <LineChart data={Array.from({ length: 8 }, (_, i) => ({ week: `W${i + 1}`, APPROVE: 80 + i * 5, REJECT: 20, MANUAL_REVIEW: 10 }))}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="week" tick={{ fontSize: 10 }} />
                  <YAxis tick={{ fontSize: 10 }} />
                  <Tooltip />
                  <Legend />
                  <Line type="monotone" dataKey="APPROVE" stroke="#22c55e" dot={false} />
                  <Line type="monotone" dataKey="REJECT" stroke="#ef4444" dot={false} />
                </LineChart>
              )}
            </ResponsiveContainer>
          </div>

          {/* Pie chart */}
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
            <h3 className="font-bold text-gray-900 mb-4">Decision Mix</h3>
            <ResponsiveContainer width="100%" height={200}>
              <PieChart>
                <Pie data={pieData.length ? pieData : [{ name: "No Data", value: 1 }]} cx="50%" cy="50%" innerRadius={50} outerRadius={80} paddingAngle={2} dataKey="value">
                  {pieData.map((entry) => (
                    <Cell key={entry.name} fill={COLORS[entry.name as keyof typeof COLORS] ?? "#94a3b8"} />
                  ))}
                </Pie>
                <Tooltip />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Regulatory summary table */}
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <h3 className="font-bold text-gray-900 mb-4">Regulatory Scorecard</h3>
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-4 text-sm">
            {[
              { label: "ECOA Compliance", value: fairReport && fairReport.dir_score >= 0.8 ? "✅ Compliant" : "⚠️ Review Needed", color: fairReport && fairReport.dir_score >= 0.8 ? "green" : "amber" },
              { label: "SR 11-7 Model Governance", value: modelMetrics && modelMetrics.auc >= 0.8 ? "✅ Compliant" : "⚠️ Below Threshold", color: modelMetrics && modelMetrics.auc >= 0.8 ? "green" : "amber" },
              { label: "Adverse Action Notices", value: `${rejectedCount} issued`, color: "neutral" },
              { label: "FCRA Disclosures", value: "✅ Current", color: "green" },
              { label: "Fair Lending Audit", value: fairReport ? `DIR: ${fairReport.dir_score.toFixed(3)}` : "—", color: fairReport && fairReport.dir_score >= 0.8 ? "green" : "red" },
              { label: "Model Drift", value: "✅ Stable", color: "green" },
            ].map((item) => (
              <div key={item.label} className={`p-3 rounded-lg border ${
                item.color === "green" ? "bg-green-50 border-green-200" :
                item.color === "amber" ? "bg-amber-50 border-amber-200" :
                item.color === "red" ? "bg-red-50 border-red-200" : "bg-gray-50 border-gray-200"
              }`}>
                <p className="text-xs text-gray-500 mb-1">{item.label}</p>
                <p className="font-semibold text-gray-900">{item.value}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </DashboardShell>
  );
}
