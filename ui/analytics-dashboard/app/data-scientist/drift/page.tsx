"use client";

import { useState } from "react";
import { DashboardShell, KpiCard, TrafficLight } from "@/components/DashboardShell";
import { useDriftReport } from "@/src/hooks";

export default function DriftPage() {
  const [dateRange, setDateRange] = useState<"7d" | "30d" | "90d" | "custom">("30d");
  const { data: report } = useDriftReport();

  if (!report) return null;

  const stableCount = report.features.filter((f) => f.status === "stable").length;
  const minorCount = report.features.filter((f) => f.status === "minor").length;
  const majorCount = report.features.filter((f) => f.status === "major").length;

  const overallColor = {
    stable: "bg-green-50 border-green-300 text-green-800",
    minor: "bg-amber-50 border-amber-300 text-amber-800",
    major: "bg-red-50 border-red-300 text-red-800",
  }[report.drift_status];

  return (
    <DashboardShell role="data_scientist" userName="Jordan Kim" dateRange={dateRange} onDateRangeChange={setDateRange}>
      <div className="space-y-6">
        {/* Overall status banner */}
        <div className={`border-2 rounded-xl p-4 flex items-center justify-between ${overallColor}`}>
          <div>
            <p className="font-bold text-lg capitalize">Overall Drift: {report.drift_status}</p>
            <p className="text-sm opacity-80">Last checked: {new Date(report.generated_at).toLocaleString()}</p>
          </div>
          <TrafficLight status={report.drift_status} />
        </div>

        {/* KPIs */}
        <div className="grid grid-cols-3 gap-4">
          <KpiCard label="Stable Features" value={stableCount.toString()} icon="🟢" color="green" />
          <KpiCard label="Minor Drift" value={minorCount.toString()} icon="🟡" color="amber" />
          <KpiCard label="Major Drift" value={majorCount.toString()} icon="🔴" color={majorCount > 0 ? "red" : "green"} />
        </div>

        {/* Feature drift table */}
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <div className="px-6 py-4 border-b flex items-center justify-between">
            <h3 className="font-bold text-gray-900">Feature Drift Report</h3>
            <button
              className="text-xs bg-red-100 hover:bg-red-200 text-red-700 font-medium px-3 py-1.5 rounded-lg transition-colors"
              onClick={() => confirm("Trigger model retraining? This will queue a new training run.") && alert("Retraining queued!")}
            >
              🔄 Trigger Retraining
            </button>
          </div>
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">Feature</th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">Status</th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">PSI</th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">KS p-value</th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">PSI Bar</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {report.features.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-16 text-center">
                    <p className="text-sm font-medium text-gray-500">All models stable.</p>
                    <p className="text-xs text-gray-400 mt-1">No drift detected in this period. Next check scheduled automatically.</p>
                  </td>
                </tr>
              ) : (
                report.features.map((f) => (
                  <tr key={f.feature} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-mono text-xs text-gray-700">{f.feature}</td>
                    <td className="px-4 py-3">
                      <span className="flex items-center gap-1.5">
                        <TrafficLight status={f.status} />
                        <span className="capitalize text-xs text-gray-600">{f.status}</span>
                      </span>
                    </td>
                    <td className="px-4 py-3 font-medium text-gray-800">{f.psi.toFixed(4)}</td>
                    <td className="px-4 py-3 text-gray-600">{f.ks_pvalue.toFixed(4)}</td>
                    <td className="px-4 py-3 w-40">
                      <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full ${
                            f.status === "stable" ? "bg-green-500" : f.status === "minor" ? "bg-amber-500" : "bg-red-500"
                          }`}
                          style={{ width: `${Math.min(f.psi / 0.3, 1) * 100}%` }}
                        />
                      </div>
                      <div className="flex justify-between text-xs text-gray-400 mt-0.5">
                        <span>0</span>
                        <span>0.10</span>
                        <span>0.25</span>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </DashboardShell>
  );
}
