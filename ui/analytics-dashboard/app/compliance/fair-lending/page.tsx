"use client";

import { useState, useEffect } from "react";
import { DashboardShell, KpiCard, StatusBadge } from "@/components/DashboardShell";
import { useFairLendingReport } from "@/src/hooks";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceLine,
  LineChart,
  Line,
  Legend,
} from "recharts";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface FairLendingHistoryRow {
  report_id: string;
  run_date: string;
  from_date: string;
  to_date: string;
  dir_minority: number | null;
  dir_female: number | null;
  approval_rate_majority: number | null;
  approval_rate_minority: number | null;
  chi_sq_p_value: number | null;
  alert_triggered: number;
}

// ---------------------------------------------------------------------------
// History hook (simple fetch with refresh)
// ---------------------------------------------------------------------------

function useFairLendingHistory(dateRange: "7d" | "30d" | "90d" | "custom") {
  const [data, setData] = useState<FairLendingHistoryRow[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const days = dateRange === "7d" ? 7 : dateRange === "90d" ? 90 : 30;
    const toDate = new Date().toISOString().slice(0, 10);
    const fromDate = new Date(Date.now() - days * 86_400_000).toISOString().slice(0, 10);
    const token =
      typeof window !== "undefined" ? (localStorage.getItem("decision_api_token") ?? "") : "";

    setLoading(true);
    fetch(
      `${process.env.NEXT_PUBLIC_DECISION_API_URL ?? "http://localhost:8000"}/v1/fair-lending/history?from_date=${fromDate}&to_date=${toDate}`,
      { headers: { Authorization: `Bearer ${token}` } }
    )
      .then((r) => (r.ok ? r.json() : Promise.reject(r.statusText)))
      .then((json) => setData(json.history ?? []))
      .catch(() => setData([]))
      .finally(() => setLoading(false));
  }, [dateRange]);

  return { data, loading };
}

export default function FairLendingPage() {
  const [dateRange, setDateRange] = useState<"7d" | "30d" | "90d" | "custom">("30d");
  const { data: report } = useFairLendingReport();
  const { data: historyRows, loading: historyLoading } = useFairLendingHistory(dateRange);

  if (!report) return null;

  const dirPass = report.dir_score >= 0.8;
  const parityPass = report.approval_parity_p_value >= 0.05;

  // Format history for recharts
  const trendData = [...historyRows]
    .sort((a, b) => a.run_date.localeCompare(b.run_date))
    .map((r) => ({
      date: r.run_date.slice(0, 10),
      dir_minority: r.dir_minority != null ? Number(r.dir_minority.toFixed(3)) : null,
      dir_female: r.dir_female != null ? Number(r.dir_female.toFixed(3)) : null,
    }));

  return (
    <DashboardShell role="compliance" userName="Morgan Lee" dateRange={dateRange} onDateRangeChange={setDateRange}>
      <div className="space-y-6">
        {/* KPIs */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <KpiCard label="DIR Score" value={report.dir_score.toFixed(3)} icon="⚖️" color={dirPass ? "green" : "red"} />
          <KpiCard label="DIR Status" value={dirPass ? "Compliant" : "FLAG"} icon={dirPass ? "✅" : "🚨"} color={dirPass ? "green" : "red"} />
          <KpiCard label="Approval Parity" value={parityPass ? "PASS" : "FAIL"} icon={parityPass ? "✅" : "⚠️"} color={parityPass ? "green" : "amber"} />
          <KpiCard label="Geographic Flags" value={`${report.geographic_flags.length} states`} icon="🗺️" color={report.geographic_flags.length > 0 ? "amber" : "green"} />
        </div>

        {/* DIR Explanation */}
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <div className="flex items-start justify-between">
            <div>
              <h3 className="font-bold text-gray-900 mb-1">Disparate Impact Ratio (DIR)</h3>
              <p className="text-sm text-gray-500">
                4/5ths rule (ECOA/HMDA): DIR must be ≥ 0.80
              </p>
            </div>
            <StatusBadge status={dirPass ? "PASS" : "FAIL"} />
          </div>
          <div className="mt-4 flex items-center gap-4">
            <div className="relative w-40 h-40">
              <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
                <circle cx="50" cy="50" r="40" fill="none" stroke="#e5e7eb" strokeWidth="12" />
                <circle
                  cx="50" cy="50" r="40" fill="none"
                  stroke={dirPass ? "#22c55e" : "#ef4444"}
                  strokeWidth="12"
                  strokeDasharray={`${report.dir_score * 251} 251`}
                  strokeLinecap="round"
                />
              </svg>
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <span className="text-2xl font-black text-gray-900">{report.dir_score.toFixed(2)}</span>
                <span className="text-xs text-gray-400">DIR</span>
              </div>
            </div>
            <div className="flex-1">
              <p className="text-sm text-gray-600 mb-2">{report.summary_text}</p>
              {report.geographic_flags.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-amber-700 mb-1">Geographic Flags:</p>
                  <div className="flex flex-wrap gap-1">
                    {report.geographic_flags.map((s) => (
                      <span key={s} className="text-xs bg-amber-100 text-amber-800 px-2 py-0.5 rounded-full font-medium">{s}</span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Approval by group */}
        <div className="grid lg:grid-cols-2 gap-6">
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
            <h3 className="font-bold text-gray-900 mb-4">Approval Rate by Demographic Group</h3>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={report.approval_by_group}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="group" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} domain={[0, 100]} />
                <Tooltip formatter={(v: number) => `${v.toFixed(1)}%`} />
                <ReferenceLine y={report.approval_by_group[0]?.approval_rate ?? 65} stroke="#3b82f6" strokeDasharray="4 2" label={{ value: "Control", fill: "#3b82f6", fontSize: 10 }} />
                <Bar dataKey="approval_rate" fill="#8b5cf6" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Approval by state */}
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
            <h3 className="font-bold text-gray-900 mb-4">Approval Rate by State (Top 7)</h3>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={report.approval_by_state}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="state" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 10 }} domain={[0, 100]} />
                <Tooltip formatter={(v: number) => `${v.toFixed(1)}%`} />
                <ReferenceLine y={62.5} stroke="#3b82f6" strokeDasharray="4 2" label={{ value: "Avg", fill: "#3b82f6", fontSize: 10 }} />
                <Bar dataKey="approval_rate" fill="#22c55e" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Parity test */}
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <div className="flex items-center justify-between mb-2">
            <h3 className="font-bold text-gray-900">Approval Parity Chi-Squared Test</h3>
            <StatusBadge status={parityPass ? "PASS" : "FAIL"} />
          </div>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-gray-500">p-value</span>
              <p className="font-semibold text-gray-900">{report.approval_parity_p_value.toFixed(4)}</p>
            </div>
            <div>
              <span className="text-gray-500">Threshold</span>
              <p className="font-semibold text-gray-900">0.05</p>
            </div>
          </div>
          <p className="text-xs text-gray-500 mt-3">
            {parityPass
              ? "No statistically significant disparity in approval rates across demographic groups (p ≥ 0.05)."
              : "Statistically significant disparity detected (p < 0.05). Review required."}
          </p>
        </div>

        {/* GAP-12: Historical DIR Trend */}
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="font-bold text-gray-900">DIR Trend History</h3>
              <p className="text-xs text-gray-400 mt-0.5">
                Disparate Impact Ratio over time — 0.80 rule threshold shown
              </p>
            </div>
            {historyLoading && (
              <span className="text-xs text-gray-400 animate-pulse">Loading…</span>
            )}
          </div>

          {trendData.length === 0 ? (
            <div className="flex items-center justify-center h-36 text-sm text-gray-400">
              No historical data available for this period.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={trendData} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 10 }}
                  tickFormatter={(d: string) => d.slice(5)}
                />
                <YAxis
                  tick={{ fontSize: 10 }}
                  domain={[0, 1.2]}
                  tickFormatter={(v: number) => v.toFixed(2)}
                />
                <Tooltip formatter={(v: number) => v?.toFixed(3)} />
                <Legend />
                <ReferenceLine
                  y={0.8}
                  stroke="#ef4444"
                  strokeDasharray="6 3"
                  label={{ value: "0.80 Threshold", fill: "#ef4444", fontSize: 10, position: "left" }}
                />
                <Line
                  type="monotone"
                  dataKey="dir_minority"
                  name="DIR (Minority)"
                  stroke="#8b5cf6"
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  connectNulls
                />
                <Line
                  type="monotone"
                  dataKey="dir_female"
                  name="DIR (Female)"
                  stroke="#06b6d4"
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  connectNulls
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>
    </DashboardShell>
  );
}
