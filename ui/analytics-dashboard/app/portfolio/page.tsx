"use client";

import { useState, useEffect, useCallback } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Legend,
  PieChart,
  Pie,
  Cell,
} from "recharts";
import {
  fetchPortfolioSnapshot,
  fetchConcentrationReport,
  fetchHeatmap,
  type PortfolioSnapshot,
  type ConcentrationReport,
  type HeatmapRow,
} from "@/lib/api";

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

function fmtPct(n: number) {
  return `${(n * 100).toFixed(2)}%`;
}

function fmtCurrency(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(n);
}

function fmtNumber(n: number) {
  return new Intl.NumberFormat("en-US").format(n);
}

function pdColor(pd: number): string {
  if (pd < 0.05) return "text-emerald-400";
  if (pd < 0.10) return "text-amber-400";
  return "text-red-400";
}

// ─────────────────────────────────────────────────────────────────────────────
// Metric Card
// ─────────────────────────────────────────────────────────────────────────────

function MetricCard({
  label,
  value,
  color = "text-white",
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div className="rounded-xl bg-slate-800 border border-slate-700 p-4">
      <p className="text-xs text-slate-400 mb-1">{label}</p>
      <p className={`text-2xl font-bold ${color}`}>{value}</p>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Concentration table
// ─────────────────────────────────────────────────────────────────────────────

const STATUS_CELL: Record<string, string> = {
  ok: "bg-emerald-900 text-emerald-300",
  warning: "bg-amber-900 text-amber-300",
  breach: "bg-red-900 text-red-300",
};

function ConcentrationTable({ rows }: { rows: HeatmapRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm text-left">
        <thead className="text-slate-400 uppercase text-xs border-b border-slate-700">
          <tr>
            <th className="py-2 px-3">Segment</th>
            <th className="py-2 px-3">Exposure %</th>
            <th className="py-2 px-3">Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label} className="border-b border-slate-800 hover:bg-slate-700/30">
              <td className="py-2 px-3 font-mono text-slate-200">{row.label}</td>
              <td className="py-2 px-3 text-slate-300">{fmtPct(row.pct_of_total)}</td>
              <td className="py-2 px-3">
                <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_CELL[row.status] ?? ""}`}>
                  {row.status.toUpperCase()}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Alerts Panel
// ─────────────────────────────────────────────────────────────────────────────

function AlertsPanel({ report }: { report: ConcentrationReport | null }) {
  if (!report) return null;
  const breaches = report.breaches;
  if (breaches.length === 0)
    return <p className="text-sm text-slate-400">No active alerts.</p>;
  return (
    <ul className="space-y-2">
      {breaches.map((b, i) => (
        <li key={i} className={`rounded-lg p-3 ${b.severity === "Breach" ? "bg-red-900/40 border border-red-700" : "bg-amber-900/40 border border-amber-700"}`}>
          <div className="flex items-center gap-2">
            <span className={`text-xs font-bold px-2 py-0.5 rounded ${b.severity === "Breach" ? "bg-red-700 text-white" : "bg-amber-600 text-white"}`}>
              {b.severity}
            </span>
            <span className="text-sm text-white font-medium">
              {b.dimension}: {b.segment_value}
            </span>
          </div>
          <p className="text-xs text-slate-300 mt-1">
            {fmtPct(b.observed_pct)} observed vs {fmtPct(b.limit_pct)} limit
            {b.excess_pct > 0 && ` (excess: ${fmtPct(b.excess_pct)})`}
          </p>
        </li>
      ))}
    </ul>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────────────

const RATING_COLORS: Record<string, string> = {
  Prime: "#10b981",
  "Near-Prime": "#f59e0b",
  Subprime: "#f97316",
  "Deep-Subprime": "#ef4444",
};

export default function PortfolioOverviewPage() {
  const [snapshot, setSnapshot] = useState<PortfolioSnapshot | null>(null);
  const [concentration, setConcentration] = useState<ConcentrationReport | null>(null);
  const [heatmapRows, setHeatmapRows] = useState<HeatmapRow[]>([]);
  const [heatmapDim, setHeatmapDim] = useState<string>("sector");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [snap, conc, hmap] = await Promise.all([
        fetchPortfolioSnapshot(),
        fetchConcentrationReport(),
        fetchHeatmap(heatmapDim),
      ]);
      setSnapshot(snap);
      setConcentration(conc);
      setHeatmapRows(hmap);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load portfolio data");
    } finally {
      setLoading(false);
    }
  }, [heatmapDim]);

  useEffect(() => {
    load();
    const timer = setInterval(load, 30_000);
    return () => clearInterval(timer);
  }, [load]);

  // Delinquency trend chart data (mock monthly trend from snapshot rates)
  const dpd30 = snapshot?.delinquency_rates?.["30dpd"] ?? 0;
  const dpd60 = snapshot?.delinquency_rates?.["60dpd"] ?? 0;
  const dpd90 = snapshot?.delinquency_rates?.["90dpd"] ?? 0;

  const trendData = Array.from({ length: 12 }, (_, i) => {
    const factor = 1 + Math.sin(i * 0.5) * 0.1;
    const label = new Date(Date.now() - (11 - i) * 30 * 86400000)
      .toLocaleDateString("en-US", { month: "short", year: "2-digit" });
    return {
      month: label,
      "30DPD": parseFloat((dpd30 * factor * 100).toFixed(2)),
      "60DPD": parseFloat((dpd60 * factor * 100).toFixed(2)),
      "90DPD": parseFloat((dpd90 * factor * 100).toFixed(2)),
    };
  });

  const pieData = snapshot
    ? Object.entries(snapshot.risk_rating_distribution).map(([name, pct]) => ({
        name,
        value: parseFloat((pct * 100).toFixed(2)),
      }))
    : [];

  return (
    <div className="min-h-screen bg-slate-900 text-white p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Portfolio Overview</h1>
          <p className="text-slate-400 text-sm mt-1">
            {snapshot ? `Last updated: ${new Date(snapshot.computed_at).toLocaleTimeString()}` : "Loading..."}
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 rounded-lg text-sm font-medium transition"
          aria-label="Refresh portfolio data"
        >
          {loading ? "Refreshing…" : "↻ Refresh"}
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-lg bg-red-900/40 border border-red-700 p-3 text-red-300 text-sm">
          {error}
        </div>
      )}

      {/* Live metrics bar */}
      {loading && !snapshot ? (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-20 rounded-xl bg-slate-800 animate-pulse" />
          ))}
        </div>
      ) : snapshot ? (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
          <MetricCard label="Total Accounts" value={fmtNumber(snapshot.total_accounts)} />
          <MetricCard
            label="WA PD"
            value={fmtPct(snapshot.wa_pd)}
            color={pdColor(snapshot.wa_pd)}
          />
          <MetricCard label="WA LGD" value={fmtPct(snapshot.wa_lgd)} />
          <MetricCard label="Expected Loss" value={fmtCurrency(snapshot.expected_loss_dollars)} />
          <MetricCard label="Approval Rate MTD" value={fmtPct(snapshot.approval_rate_mtd)} />
        </div>
      ) : null}

      {/* Main grid */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Left column — charts */}
        <div className="xl:col-span-2 space-y-6">
          {/* DPD Trend */}
          <div className="rounded-xl bg-slate-800 border border-slate-700 p-4">
            <h2 className="text-sm font-semibold text-slate-300 mb-4">Delinquency Trend (30/60/90 DPD)</h2>
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={trendData} aria-label="Delinquency trend chart">
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="month" tick={{ fill: "#94a3b8", fontSize: 11 }} />
                <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} tickFormatter={(v) => `${v}%`} />
                <Tooltip formatter={(v: number) => `${v}%`} contentStyle={{ background: "#1e293b", border: "none" }} />
                <Legend wrapperStyle={{ color: "#94a3b8", fontSize: 12 }} />
                <Line type="monotone" dataKey="30DPD" stroke="#f59e0b" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="60DPD" stroke="#f97316" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="90DPD" stroke="#ef4444" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* Risk Distribution Pie */}
          <div className="rounded-xl bg-slate-800 border border-slate-700 p-4">
            <h2 className="text-sm font-semibold text-slate-300 mb-4">Risk Rating Distribution</h2>
            <div className="flex items-center gap-6">
              <ResponsiveContainer width={200} height={200}>
                <PieChart aria-label="Risk rating distribution pie chart">
                  <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} label={false}>
                    {pieData.map((entry) => (
                      <Cell key={entry.name} fill={RATING_COLORS[entry.name] ?? "#6366f1"} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(v: number) => `${v}%`} contentStyle={{ background: "#1e293b", border: "none" }} />
                </PieChart>
              </ResponsiveContainer>
              <ul className="space-y-2 text-sm">
                {pieData.map((d) => (
                  <li key={d.name} className="flex items-center gap-2">
                    <span className="inline-block w-3 h-3 rounded-full" style={{ background: RATING_COLORS[d.name] ?? "#6366f1" }} />
                    <span className="text-slate-300">{d.name}</span>
                    <span className="text-white font-medium ml-auto">{d.value}%</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {/* Concentration Heatmap */}
          <div className="rounded-xl bg-slate-800 border border-slate-700 p-4">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-slate-300">Concentration Heatmap</h2>
              <select
                value={heatmapDim}
                onChange={(e) => setHeatmapDim(e.target.value)}
                className="bg-slate-700 text-white text-xs rounded px-2 py-1 border border-slate-600"
                aria-label="Select concentration dimension"
              >
                {["sector", "state", "risk_grade", "product_type"].map((d) => (
                  <option key={d} value={d}>{d}</option>
                ))}
              </select>
            </div>
            <ConcentrationTable rows={heatmapRows} />
          </div>
        </div>

        {/* Right column — alerts */}
        <div className="rounded-xl bg-slate-800 border border-slate-700 p-4 h-fit">
          <h2 className="text-sm font-semibold text-slate-300 mb-4">Active Alerts</h2>
          <AlertsPanel report={concentration} />
        </div>
      </div>
    </div>
  );
}
