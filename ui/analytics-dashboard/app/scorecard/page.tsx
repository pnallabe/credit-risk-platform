"use client";

import { useState, useEffect } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ScatterChart,
  Scatter,
  ReferenceLine,
  Cell,
} from "recharts";
import { fetchScorecard, type ScorecardRow } from "@/lib/api";

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

const MODEL_NAMES: Record<string, string> = {
  cc_pd_v1: "Consumer",
  smb_pd_v1: "SMB",
  commercial_pd_v1: "Commercial",
};

function ivLabel(iv: number): { label: string; cls: string } {
  if (iv >= 0.3) return { label: "Strong", cls: "bg-emerald-700 text-emerald-200" };
  if (iv >= 0.1) return { label: "Medium", cls: "bg-amber-700 text-amber-200" };
  return { label: "Weak", cls: "bg-slate-600 text-slate-300" };
}

function pointColor(pts: number): string {
  if (pts > 0) return "text-emerald-400";
  if (pts < 0) return "text-red-400";
  return "text-slate-400";
}

// ─────────────────────────────────────────────────────────────────────────────
// Feature group helper
// ─────────────────────────────────────────────────────────────────────────────

function groupByFeature(rows: ScorecardRow[]): Record<string, ScorecardRow[]> {
  const map: Record<string, ScorecardRow[]> = {};
  for (const row of rows) {
    if (!map[row.feature]) map[row.feature] = [];
    map[row.feature].push(row);
  }
  return map;
}

// ─────────────────────────────────────────────────────────────────────────────
// WoE bin bar chart (shown on feature expand)
// ─────────────────────────────────────────────────────────────────────────────

function FeatureBinChart({ bins }: { bins: ScorecardRow[] }) {
  const data = bins.map((b) => ({ bin: b.bin_label, woe: parseFloat(b.woe.toFixed(4)), count: b.count }));
  return (
    <div className="mt-3 ml-6">
      <ResponsiveContainer width="100%" height={140}>
        <BarChart data={data} aria-label={`WoE per bin chart`}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis dataKey="bin" tick={{ fill: "#94a3b8", fontSize: 10 }} />
          <YAxis yAxisId="woe" tick={{ fill: "#94a3b8", fontSize: 10 }} />
          <YAxis yAxisId="count" orientation="right" tick={{ fill: "#94a3b8", fontSize: 10 }} />
          <Tooltip contentStyle={{ background: "#1e293b", border: "none" }} />
          <Bar yAxisId="woe" dataKey="woe" fill="#6366f1" name="WoE" />
          <Bar yAxisId="count" dataKey="count" fill="#94a3b8" name="Count" opacity={0.5} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Scorecard Table
// ─────────────────────────────────────────────────────────────────────────────

function ScorecardTable({
  rows,
  search,
}: {
  rows: ScorecardRow[];
  search: string;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const grouped = groupByFeature(rows);

  // Sort by feature_iv descending, filter by search
  const features = Object.keys(grouped)
    .filter((f) => !search || f.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => (grouped[b][0]?.feature_iv ?? 0) - (grouped[a][0]?.feature_iv ?? 0));

  if (features.length === 0)
    return <p className="text-slate-400 text-sm p-4">No features found.</p>;

  return (
    <table className="w-full text-sm text-left" aria-label="WoE Scorecard">
      <caption className="sr-only">WoE Scorecard table sorted by Information Value</caption>
      <thead className="text-slate-400 uppercase text-xs border-b border-slate-700">
        <tr>
          <th className="py-2 px-3">Feature</th>
          <th className="py-2 px-3">Bin Range</th>
          <th className="py-2 px-3">WoE</th>
          <th className="py-2 px-3">Points</th>
          <th className="py-2 px-3">IV</th>
        </tr>
      </thead>
      <tbody>
        {features.map((feat) => {
          const bins = grouped[feat];
          const featureIv = bins[0]?.feature_iv ?? 0;
          const { label: ivLbl, cls: ivCls } = ivLabel(featureIv);
          const isExpanded = expanded === feat;
          return (
            <>
              {/* Feature header row */}
              <tr
                key={`${feat}-header`}
                className="border-b border-slate-700 bg-slate-800/60 cursor-pointer hover:bg-slate-700/40"
                onClick={() => setExpanded(isExpanded ? null : feat)}
                aria-expanded={isExpanded}
              >
                <td className="py-2 px-3 font-semibold text-slate-200" colSpan={4}>
                  {isExpanded ? "▼" : "▶"} {feat}
                </td>
                <td className="py-2 px-3">
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${ivCls}`}>
                    {ivLbl} ({featureIv.toFixed(3)})
                  </span>
                </td>
              </tr>

              {/* Bin rows */}
              {bins.map((row, i) => (
                <tr key={`${feat}-bin-${i}`} className={`border-b border-slate-800 ${isExpanded ? "" : "hidden"}`}>
                  <td className="py-1.5 px-3 pl-8 text-slate-400 text-xs" />
                  <td className="py-1.5 px-3 font-mono text-xs text-slate-300">{row.bin_label}</td>
                  <td className="py-1.5 px-3 font-mono text-xs text-slate-300">{row.woe.toFixed(4)}</td>
                  <td className={`py-1.5 px-3 font-bold text-xs ${pointColor(row.points)}`}>{row.points}</td>
                  <td className="py-1.5 px-3 text-xs text-slate-400">{row.iv.toFixed(4)}</td>
                </tr>
              ))}

              {/* Expanded bin chart */}
              {isExpanded && (
                <tr key={`${feat}-chart`} className="border-b border-slate-700">
                  <td colSpan={5}>
                    <FeatureBinChart bins={bins} />
                  </td>
                </tr>
              )}
            </>
          );
        })}
      </tbody>
    </table>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────────────

export default function ScorecardExplorerPage() {
  const [selectedModel, setSelectedModel] = useState<string>("cc_pd_v1");
  const [rows, setRows] = useState<ScorecardRow[]>([]);
  const [scorecardType, setScorecardType] = useState<string>("woe");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchScorecard(selectedModel)
      .then((data) => {
        setRows(data.rows ?? []);
        setScorecardType(data.scorecard_type ?? "woe");
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [selectedModel]);

  // Download CSV
  const downloadCsv = () => {
    if (!rows.length) return;
    const headers = ["feature", "bin_label", "bin_lower", "bin_upper", "count", "event_rate", "woe", "iv", "points", "feature_iv", "iv_label"];
    const lines = [
      headers.join(","),
      ...rows.map((r) =>
        [r.feature, r.bin_label, r.bin_lower, r.bin_upper, r.count, r.event_rate, r.woe, r.iv, r.points, r.feature_iv, r.iv_label].join(",")
      ),
    ];
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${selectedModel}_scorecard.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="min-h-screen bg-slate-900 text-white p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Scorecard Explorer</h1>
          <p className="text-slate-400 text-sm mt-1">
            WoE scorecards with Information Value and bin-level analysis
          </p>
        </div>
        <button
          onClick={downloadCsv}
          disabled={!rows.length}
          className="px-4 py-2 bg-emerald-700 hover:bg-emerald-600 disabled:opacity-40 rounded-lg text-sm font-medium transition"
          aria-label="Download scorecard CSV"
        >
          ↓ Download CSV
        </button>
      </div>

      {/* Segment tabs */}
      <div className="flex gap-2 mb-6" role="tablist">
        {Object.entries(MODEL_NAMES).map(([key, label]) => (
          <button
            key={key}
            role="tab"
            aria-selected={selectedModel === key}
            onClick={() => setSelectedModel(key)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition ${
              selectedModel === key
                ? "bg-indigo-600 text-white"
                : "bg-slate-800 text-slate-300 hover:bg-slate-700"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {error && (
        <div className="mb-4 rounded-lg bg-red-900/40 border border-red-700 p-3 text-red-300 text-sm">
          {error}
        </div>
      )}

      <div className="flex gap-6">
        {/* Left: Scorecard Table */}
        <div className="flex-1 rounded-xl bg-slate-800 border border-slate-700 overflow-hidden">
          <div className="p-3 border-b border-slate-700">
            <input
              type="text"
              placeholder="Search features…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full bg-slate-700 text-white text-sm rounded px-3 py-1.5 border border-slate-600 placeholder-slate-500"
              aria-label="Search features"
            />
          </div>
          {loading ? (
            <div className="p-6 space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="h-8 rounded bg-slate-700 animate-pulse" />
              ))}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <ScorecardTable rows={rows} search={search} />
            </div>
          )}
        </div>

        {/* Right: Performance Metrics */}
        <div className="w-64 rounded-xl bg-slate-800 border border-slate-700 p-4 h-fit space-y-4">
          <h2 className="text-sm font-semibold text-slate-300">Performance Metrics</h2>
          <div>
            <p className="text-xs text-slate-400">Scorecard Type</p>
            <p className="font-medium text-white capitalize">{scorecardType}</p>
          </div>
          <div>
            <p className="text-xs text-slate-400">Features</p>
            <p className="font-medium text-white">{Object.keys(groupByFeature(rows)).length}</p>
          </div>
          <div>
            <p className="text-xs text-slate-400">Strong IV Features (≥0.30)</p>
            <p className="font-medium text-emerald-400">
              {Object.values(groupByFeature(rows)).filter((bins) => (bins[0]?.feature_iv ?? 0) >= 0.3).length}
            </p>
          </div>
          <div>
            <p className="text-xs text-slate-400">Total Bins</p>
            <p className="font-medium text-white">{rows.length}</p>
          </div>
          <div>
            <p className="text-xs text-slate-400">Model</p>
            <p className="font-mono text-xs text-slate-300">{selectedModel}</p>
          </div>
        </div>
      </div>
    </div>
  );
}
