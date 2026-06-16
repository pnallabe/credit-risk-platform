"use client";

import { useState } from "react";
import { DashboardShell, KpiCard, StatusBadge } from "@/components/DashboardShell";
import { useModelMetrics } from "@/src/hooks";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  CartesianGrid,
  Legend,
} from "recharts";

export default function ModelPerformancePage() {
  const [dateRange, setDateRange] = useState<"7d" | "30d" | "90d" | "custom">("30d");
  const { data: metrics } = useModelMetrics();

  if (!metrics) return null;

  const cr = metrics.credit_risk;
  const fd = metrics.fraud_detection;

  return (
    <DashboardShell role="risk_analyst" userName="Sam Rivera" dateRange={dateRange} onDateRangeChange={setDateRange}>
      <div className="space-y-6">
        {/* Credit Risk Model KPIs */}
        <div>
          <h2 className="font-bold text-gray-900 mb-3">Credit Risk Model (v{cr.version})</h2>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <KpiCard label="AUC" value={cr.auc.toFixed(3)} icon="📈" color={cr.auc >= 0.75 ? "green" : "red"} />
            <KpiCard label="KS Statistic" value={cr.ks.toFixed(3)} icon="📉" color={cr.ks >= 0.35 ? "green" : "red"} />
            <KpiCard label="Precision" value={cr.precision.toFixed(3)} icon="🎯" color="blue" />
            <KpiCard label="F1 Score" value={cr.f1.toFixed(3)} icon="⚡" color="purple" />
          </div>
        </div>

        {/* Fraud Detection KPIs */}
        <div>
          <h2 className="font-bold text-gray-900 mb-3">Fraud Detection Model (v{fd.version})</h2>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <KpiCard label="AUC" value={fd.auc.toFixed(3)} icon="📈" color={fd.auc >= 0.8 ? "green" : "red"} />
            <KpiCard label="Precision" value={fd.precision.toFixed(3)} icon="🎯" color={fd.precision >= 0.85 ? "green" : "red"} />
            <KpiCard label="Recall" value={fd.recall.toFixed(3)} icon="🔍" color="blue" />
            <KpiCard label="F1 Score" value={fd.f1.toFixed(3)} icon="⚡" color="purple" />
          </div>
        </div>

        {/* ROC Curve + Feature Importances */}
        <div className="grid lg:grid-cols-2 gap-6">
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
            <h3 className="font-bold text-gray-900 mb-1">ROC Curve</h3>
            <p className="text-xs text-gray-400 mb-4">AUC = {cr.auc.toFixed(3)}</p>
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={metrics.roc_curve}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="fpr" tick={{ fontSize: 10 }} label={{ value: "FPR", position: "insideBottom", offset: -2, fontSize: 11 }} />
                <YAxis tick={{ fontSize: 10 }} label={{ value: "TPR", angle: -90, position: "insideLeft", fontSize: 11 }} />
                <Tooltip formatter={(v: number) => v.toFixed(3)} />
                <Line type="monotone" dataKey="tpr" stroke="#3b82f6" dot={false} strokeWidth={2} name="Model" />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
            <h3 className="font-bold text-gray-900 mb-4">Feature Importances (SHAP)</h3>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={metrics.feature_importances.slice(0, 8)} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" tick={{ fontSize: 10 }} />
                <YAxis dataKey="feature" type="category" tick={{ fontSize: 10 }} width={130} />
                <Tooltip formatter={(v: number) => (v * 100).toFixed(1) + "%"} />
                <Bar dataKey="importance" fill="#6366f1" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* SLO Summary */}
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <h3 className="font-bold text-gray-900 mb-4">SLO Status</h3>
          <div className="flex flex-wrap gap-4">
            {[
              { label: "AUC ≥ 0.75", pass: cr.auc >= 0.75 },
              { label: "KS ≥ 0.35", pass: cr.ks >= 0.35 },
              { label: "Precision ≥ 0.85 (Fraud)", pass: fd.precision >= 0.85 },
              { label: "AUC ≥ 0.80 (Fraud)", pass: fd.auc >= 0.80 },
            ].map((slo) => (
              <div key={slo.label} className="flex items-center gap-2">
                <StatusBadge status={slo.pass ? "PASS" : "FAIL"} />
                <span className="text-sm text-gray-700">{slo.label}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </DashboardShell>
  );
}
