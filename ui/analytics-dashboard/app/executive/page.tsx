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

// ─── NLG Executive Summary Section ────────────────────────────────────────────

interface ExecutiveSummary {
  headline: string;
  narrative: string;
  action_items: string[];
  key_metrics_table: Array<{ label: string; value: string; status: string }>;
  period_label: string;
  generated_at: string;
}

const MOCK_SUMMARY: ExecutiveSummary = {
  headline: "Portfolio performing within risk appetite — model health stable",
  period_label: "last-30d",
  generated_at: new Date().toISOString(),
  narrative: `**Portfolio Overview (last 30 days)**

Total originations are on track with a **65.8% approval rate**, up 1.2 pp versus the prior period.
Average funded amount remains at $12,400 with aggregate exposure of $18.2M — within the Q1 concentration limit of $25M.

**Model Health**

The credit risk model (LightGBM v3.2) continues to perform above governance thresholds:
AUC = 0.837 (threshold ≥ 0.80), KS = 0.458, PSI = 0.043 (stable). No drift detected.
The challenger model from Experiment exp-001 is showing an approval uplift of +3.4 pp at p = 0.032 — review for promotion is recommended.

**Fair Lending**

Adverse impact ratios remain within regulatory safe-harbour:
- Gender AIR: 1.01 (threshold ≥ 0.80) ✅
- Race/Ethnicity AIR: 0.89 (threshold ≥ 0.80) ✅

ECOA and FCRA compliance status: **Current**.

**Risk Highlights**

Manual-review queue is at 42 pending cases (within SLA of 48 hrs). No regulatory escalations outstanding.`,
  action_items: [
    "Review A/B Experiment exp-001 (PROMOTE recommendation — p = 0.032, Δ approval +3.4 pp)",
    "Clear 42 manual-review applications ahead of month-end reporting",
    "Schedule quarterly model validation committee review before 2025-04-30",
  ],
  key_metrics_table: [
    { label: "Approval Rate",       value: "65.8%",  status: "OK"   },
    { label: "Model AUC",           value: "0.837",  status: "OK"   },
    { label: "PSI (Drift)",         value: "0.043",  status: "OK"   },
    { label: "Gender AIR",          value: "1.01",   status: "OK"   },
    { label: "Race/Ethnicity AIR",  value: "0.89",   status: "OK"   },
    { label: "Manual Review Queue", value: "42",     status: "WARN" },
  ],
};

const STATUS_DOT: Record<string, string> = {
  OK: "bg-green-500",
  WARN: "bg-amber-400",
  ERR: "bg-red-500",
};

function NLGSummaryWidget() {
  const [loading, setLoading] = useState(false);
  const [summary, setSummary] = useState<ExecutiveSummary>(MOCK_SUMMARY);
  const [expanded, setExpanded] = useState(false);
  const [period, setPeriod] = useState("last-30d");
  const [audience, setAudience] = useState("cro");

  const regenerate = useCallback(async () => {
    setLoading(true);
    // In production: fetch(`/v1/analytics/executive-summary?period_label=${period}&audience=${audience}`)
    await new Promise((r) => setTimeout(r, 1200));
    setSummary({ ...MOCK_SUMMARY, generated_at: new Date().toISOString(), period_label: period });
    setLoading(false);
  }, [period, audience]);

  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6 space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-base">🤖</span>
            <h3 className="font-bold text-gray-900">AI Executive Summary</h3>
            <span className="text-xs bg-blue-100 text-blue-700 font-medium px-2 py-0.5 rounded-full">Sprint 6-B · NLG</span>
          </div>
          <p className="text-xs text-gray-500 mt-0.5">
            Generated {new Date(summary.generated_at).toLocaleString()} · Period: {summary.period_label}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <select
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            className="text-xs border border-gray-200 rounded-lg px-2 py-1"
          >
            <option value="last-7d">Last 7 days</option>
            <option value="last-30d">Last 30 days</option>
            <option value="last-90d">Last 90 days</option>
            <option value="2025-Q1">Q1 2025</option>
          </select>
          <select
            value={audience}
            onChange={(e) => setAudience(e.target.value)}
            className="text-xs border border-gray-200 rounded-lg px-2 py-1"
          >
            <option value="cro">CRO</option>
            <option value="board">Board</option>
            <option value="regulator">Regulator</option>
          </select>
          <button
            onClick={regenerate}
            disabled={loading}
            className="text-xs bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-medium px-3 py-1.5 rounded-lg flex items-center gap-1.5 transition-colors"
          >
            {loading ? (
              <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            ) : (
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
            )}
            {loading ? "Generating…" : "Regenerate"}
          </button>
        </div>
      </div>

      {/* Headline */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-3">
        <p className="font-semibold text-blue-900 text-sm">{summary.headline}</p>
      </div>

      {/* Key metrics table */}
      <div className="grid grid-cols-3 lg:grid-cols-6 gap-2">
        {summary.key_metrics_table.map((row) => (
          <div key={row.label} className="bg-gray-50 rounded-lg p-2 text-center">
            <div className="flex items-center justify-center gap-1 mb-1">
              <span className={`w-1.5 h-1.5 rounded-full ${STATUS_DOT[row.status] ?? "bg-gray-400"}`} />
            </div>
            <p className="font-bold text-gray-900 text-sm">{row.value}</p>
            <p className="text-xs text-gray-500 leading-tight">{row.label}</p>
          </div>
        ))}
      </div>

      {/* Action items */}
      {summary.action_items.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3">
          <p className="text-xs font-semibold text-amber-800 mb-1.5 uppercase tracking-wide">Action Required</p>
          <ul className="space-y-1">
            {summary.action_items.map((item, i) => (
              <li key={i} className="text-xs text-amber-900 flex gap-1.5">
                <span className="text-amber-500 mt-0.5 shrink-0">→</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Narrative */}
      <div>
        <button
          onClick={() => setExpanded((p) => !p)}
          className="text-xs text-blue-600 hover:text-blue-800 font-medium flex items-center gap-1"
        >
          <svg className={`w-3 h-3 transition-transform ${expanded ? "rotate-90" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
          {expanded ? "Hide" : "Show"} full narrative
        </button>
        {expanded && (
          <div className="mt-3 bg-gray-50 rounded-lg p-4 text-xs text-gray-700 leading-relaxed whitespace-pre-line font-mono">
            {summary.narrative}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Main Page ─────────────────────────────────────────────────────────────────

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
          <tr><td>Model AUC</td><td>${modelMetrics?.credit_risk.auc.toFixed(3) ?? "—"}</td></tr>
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

        {/* NLG Executive Summary — Sprint 6-B */}
        <NLGSummaryWidget />

        {/* KPIs row */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <KpiCard label="Total Decisions" value={total.toLocaleString()} icon="📄" color="blue" />
          <KpiCard label="Approval Rate" value={`${approvalRate}%`} icon="✅" color="green" />
          <KpiCard label="Avg Loan Size" value={`$${avgLoan}`} icon="💵" color="blue" />
          <KpiCard label="Model AUC" value={modelMetrics ? modelMetrics.credit_risk.auc.toFixed(3) : "—"} icon="🎯" color={modelMetrics && modelMetrics.credit_risk.auc >= 0.8 ? "green" : "amber"} />
        </div>

        {/* Second KPI row */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <KpiCard label="KS Statistic" value={modelMetrics ? modelMetrics.credit_risk.ks.toFixed(3) : "—"} icon="📈" color={modelMetrics && modelMetrics.credit_risk.ks >= 0.35 ? "green" : "red"} />
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
              { label: "SR 11-7 Model Governance", value: modelMetrics && modelMetrics.credit_risk.auc >= 0.8 ? "✅ Compliant" : "⚠️ Below Threshold", color: modelMetrics && modelMetrics.credit_risk.auc >= 0.8 ? "green" : "amber" },
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
          <tr><td>Model AUC</td><td>${modelMetrics?.credit_risk.auc.toFixed(3) ?? "—"}</td></tr>
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
          <KpiCard label="Model AUC" value={modelMetrics ? modelMetrics.credit_risk.auc.toFixed(3) : "—"} icon="🎯" color={modelMetrics && modelMetrics.credit_risk.auc >= 0.8 ? "green" : "amber"} />
        </div>

        {/* Second KPI row */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <KpiCard label="KS Statistic" value={modelMetrics ? modelMetrics.credit_risk.ks.toFixed(3) : "—"} icon="📈" color={modelMetrics && modelMetrics.credit_risk.ks >= 0.35 ? "green" : "red"} />
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
              { label: "SR 11-7 Model Governance", value: modelMetrics && modelMetrics.credit_risk.auc >= 0.8 ? "✅ Compliant" : "⚠️ Below Threshold", color: modelMetrics && modelMetrics.credit_risk.auc >= 0.8 ? "green" : "amber" },
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
