"use client";

import { useState } from "react";
import { DashboardShell, KpiCard } from "@/components/DashboardShell";
import { useDecisionsData } from "@/src/hooks";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  LineChart,
  Line,
  Legend,
  ReferenceLine,
} from "recharts";

function buildHistogramBins(values: number[], numBins = 20) {
  if (values.length === 0) return [];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const step = (max - min) / numBins || 0.05;
  const bins = Array.from({ length: numBins }, (_, i) => ({
    range: `${((min + i * step) * 100).toFixed(0)}–${((min + (i + 1) * step) * 100).toFixed(0)}%`,
    count: 0,
  }));
  for (const v of values) {
    const idx = Math.min(Math.floor((v - min) / step), numBins - 1);
    bins[idx].count++;
  }
  return bins;
}

function KsChart({ data }: { data: { thresh: number; tpr: number; fpr: number; ks: number }[] }) {
  if (!data.length) return null;
  const maxKS = data.reduce((a, b) => (a.ks > b.ks ? a : b));
  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="thresh" tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} tick={{ fontSize: 10 }} />
        <YAxis tick={{ fontSize: 10 }} domain={[0, 1]} />
        <Tooltip />
        <Legend />
        <Line type="monotone" dataKey="tpr" name="TPR (cumul.)" stroke="#3b82f6" dot={false} />
        <Line type="monotone" dataKey="fpr" name="FPR (cumul.)" stroke="#ef4444" dot={false} />
        <ReferenceLine x={maxKS.thresh} stroke="#8b5cf6" strokeDasharray="4 2" label={{ value: `KS=${(maxKS.ks * 100).toFixed(1)}%`, fill: "#8b5cf6", fontSize: 10 }} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export default function CreditRiskPage() {
  const [dateRange, setDateRange] = useState<"7d" | "30d" | "90d" | "custom">("30d");
  const { data: decisionsData } = useDecisionsData(dateRange);

  const decisions = decisionsData?.decisions ?? [];
  const pdScores = decisions.map((d) => d.pd_score ?? 0);
  const approved = decisions.filter((d) => d.decision === "APPROVE");
  const rejected = decisions.filter((d) => d.decision === "REJECT");

  const histogramAll = buildHistogramBins(pdScores);
  const histogramApproved = buildHistogramBins(approved.map((d) => d.pd_score ?? 0));
  const histogramRejected = buildHistogramBins(rejected.map((d) => d.pd_score ?? 0));

  // Simple KS curve mock data
  const ksData = Array.from({ length: 21 }, (_, i) => {
    const thresh = i / 20;
    const tpr = Math.min(1, thresh * 1.8);
    const fpr = thresh * thresh;
    return { thresh, tpr, fpr, ks: tpr - fpr };
  });

  const avgPd = pdScores.length ? pdScores.reduce((a, b) => a + b, 0) / pdScores.length : 0;
  const highRiskCount = pdScores.filter((p) => p > 0.5).length;

  return (
    <DashboardShell role="risk_analyst" userName="Sam Park" dateRange={dateRange} onDateRangeChange={setDateRange}>
      <div className="space-y-6">
        {/* KPIs */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <KpiCard label="Applications" value={decisions.length.toString()} icon="📄" color="blue" />
          <KpiCard label="Avg PD Score" value={`${(avgPd * 100).toFixed(1)}%`} icon="📊" color="amber" />
          <KpiCard label="High Risk (>50%)" value={highRiskCount.toString()} icon="⚠️" color={highRiskCount > 20 ? "red" : "green"} />
          <KpiCard label="KS Statistic" value="43.2%" icon="📈" color="green" />
        </div>

        {/* PD Histograms */}
        <div className="grid lg:grid-cols-2 gap-6">
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
            <h3 className="font-bold text-gray-900 mb-4">PD Score Distribution — Approved</h3>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={histogramApproved}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="range" tick={{ fontSize: 8 }} />
                <YAxis tick={{ fontSize: 10 }} />
                <Tooltip />
                <Bar dataKey="count" fill="#22c55e" radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
            <h3 className="font-bold text-gray-900 mb-4">PD Score Distribution — Rejected</h3>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={histogramRejected}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="range" tick={{ fontSize: 8 }} />
                <YAxis tick={{ fontSize: 10 }} />
                <Tooltip />
                <Bar dataKey="count" fill="#ef4444" radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* All applications PD histogram */}
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <h3 className="font-bold text-gray-900 mb-4">All Applications – PD Score Distribution</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={histogramAll}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="range" tick={{ fontSize: 8 }} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip />
              <ReferenceLine x="50–55%" stroke="#ef4444" strokeDasharray="4 2" label={{ value: "High Risk", fill: "#ef4444", fontSize: 10 }} />
              <Bar dataKey="count" fill="#8b5cf6" radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* KS curve */}
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <h3 className="font-bold text-gray-900 mb-4">Kolmogorov–Smirnov Curve</h3>
          <KsChart data={ksData} />
        </div>
      </div>
    </DashboardShell>
  );
}
