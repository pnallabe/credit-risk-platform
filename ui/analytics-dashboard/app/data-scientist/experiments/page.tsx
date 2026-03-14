"use client";

import { useState } from "react";
import { DashboardShell } from "@/components/DashboardShell";

interface MlflowRun {
  run_id: string;
  name: string;
  status: "FINISHED" | "RUNNING" | "FAILED";
  start_time: string;
  auc: number;
  ks: number;
  f1: number;
  precision: number;
  recall: number;
  params: Record<string, string | number>;
}

const MOCK_RUNS: MlflowRun[] = [
  { run_id: "run-a1b2", name: "lgbm-v3-baseline", status: "FINISHED", start_time: "2025-02-01T09:00:00", auc: 0.823, ks: 0.441, f1: 0.712, precision: 0.742, recall: 0.684, params: { n_estimators: 300, max_depth: 6, learning_rate: 0.05, min_child_samples: 30 } },
  { run_id: "run-c3d4", name: "lgbm-v3-tuned", status: "FINISHED", start_time: "2025-02-03T14:30:00", auc: 0.837, ks: 0.458, f1: 0.724, precision: 0.755, recall: 0.696, params: { n_estimators: 500, max_depth: 8, learning_rate: 0.03, min_child_samples: 20 } },
  { run_id: "run-e5f6", name: "xgb-experiment", status: "FINISHED", start_time: "2025-02-05T11:00:00", auc: 0.801, ks: 0.418, f1: 0.698, precision: 0.721, recall: 0.676, params: { n_estimators: 200, max_depth: 5, learning_rate: 0.1, min_child_samples: 50 } },
  { run_id: "run-g7h8", name: "lgbm-v4-draft", status: "RUNNING", start_time: "2025-02-08T08:00:00", auc: 0, ks: 0, f1: 0, precision: 0, recall: 0, params: { n_estimators: 800, max_depth: 10, learning_rate: 0.01, min_child_samples: 15 } },
];

const METRICS = ["auc", "ks", "f1", "precision", "recall"] as const;

const STATUS_STYLE: Record<string, string> = {
  FINISHED: "bg-green-100 text-green-800",
  RUNNING: "bg-blue-100 text-blue-800 animate-pulse",
  FAILED: "bg-red-100 text-red-800",
};

export default function ExperimentsPage() {
  const [dateRange, setDateRange] = useState<"7d" | "30d" | "90d" | "custom">("30d");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [sortMetric, setSortMetric] = useState<"auc" | "ks" | "f1">("auc");

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else if (next.size < 3) next.add(id);
      return next;
    });
  };

  const sortedRuns = [...MOCK_RUNS].sort((a, b) => b[sortMetric] - a[sortMetric]);
  const compareRuns = MOCK_RUNS.filter((r) => selected.has(r.run_id));

  return (
    <DashboardShell role="data_scientist" userName="Jordan Kim" dateRange={dateRange} onDateRangeChange={setDateRange}>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-gray-900">MLflow Experiment Browser</h2>
            <p className="text-sm text-gray-500">Select up to 3 runs to compare side-by-side</p>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <label className="text-gray-600">Sort by:</label>
            <select value={sortMetric} onChange={(e) => setSortMetric(e.target.value as typeof sortMetric)} className="border border-gray-300 rounded px-2 py-1 text-sm">
              <option value="auc">AUC</option>
              <option value="ks">KS</option>
              <option value="f1">F1</option>
            </select>
          </div>
        </div>

        {/* Run table */}
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-3 w-10" />
                <th className="px-4 py-3 text-left font-semibold text-gray-600">Run Name</th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">Status</th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">AUC</th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">KS</th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">F1</th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">Started</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {sortedRuns.map((run) => (
                <tr key={run.run_id} className={`hover:bg-gray-50 ${selected.has(run.run_id) ? "bg-blue-50" : ""}`}>
                  <td className="px-4 py-3">
                    <input
                      type="checkbox"
                      checked={selected.has(run.run_id)}
                      onChange={() => toggleSelect(run.run_id)}
                      disabled={!selected.has(run.run_id) && selected.size >= 3}
                      className="rounded border-gray-300"
                    />
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-800">{run.name}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs font-semibold px-2 py-1 rounded-full ${STATUS_STYLE[run.status]}`}>{run.status}</span>
                  </td>
                  {METRICS.map((m) => (
                    <td key={m} className="px-4 py-3 font-semibold text-gray-800">
                      {run.status === "RUNNING" ? <span className="text-gray-400">—</span> : (run[m] * 100).toFixed(1) + "%"}
                    </td>
                  )).slice(0, 3)}
                  <td className="px-4 py-3 text-gray-500 text-xs">{new Date(run.start_time).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Comparison panel */}
        {compareRuns.length >= 2 && (
          <div className="bg-white rounded-xl border border-blue-200 shadow-sm overflow-hidden">
            <div className="px-6 py-4 border-b bg-blue-50">
              <h3 className="font-bold text-blue-900">Side-by-Side Comparison ({compareRuns.length} runs)</h3>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b">
                  <tr>
                    <th className="px-4 py-3 text-left font-semibold text-gray-600">Metric / Param</th>
                    {compareRuns.map((r) => (
                      <th key={r.run_id} className="px-4 py-3 text-left font-semibold text-gray-600">
                        <span className="font-mono text-xs block">{r.name}</span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {METRICS.map((m) => {
                    const best = Math.max(...compareRuns.map((r) => r[m]));
                    return (
                      <tr key={m} className="hover:bg-gray-50">
                        <td className="px-4 py-3 text-gray-600 font-medium uppercase text-xs">{m}</td>
                        {compareRuns.map((r) => (
                          <td key={r.run_id} className={`px-4 py-3 font-semibold ${r[m] === best ? "text-green-700" : "text-gray-700"}`}>
                            {r.status === "RUNNING" ? "—" : (r[m] * 100).toFixed(2) + "%"}
                            {r[m] === best && r.status !== "RUNNING" && <span className="ml-1 text-xs text-green-600">↑ best</span>}
                          </td>
                        ))}
                      </tr>
                    );
                  })}
                  {Object.keys(compareRuns[0].params).map((p) => (
                    <tr key={p} className="hover:bg-gray-50 bg-gray-50/50">
                      <td className="px-4 py-3 font-mono text-xs text-gray-500">{p}</td>
                      {compareRuns.map((r) => (
                        <td key={r.run_id} className="px-4 py-3 font-mono text-xs text-gray-700">{r.params[p]}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </DashboardShell>
  );
}
