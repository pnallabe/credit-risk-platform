"use client";

import { useState, useMemo } from "react";
import { DashboardShell } from "@/components/DashboardShell";
import { useDecisionsData } from "@/src/hooks";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Legend,
} from "recharts";

const FEATURES = ["annual_income", "credit_score", "dti_ratio", "loan_amount", "employment_years", "num_accounts", "derogatory_marks"];

function buildCorrelationMatrix(features: string[]) {
  return features.map((f1) =>
    features.map((f2) => {
      if (f1 === f2) return 1.0;
      const seed = (f1.length * 7 + f2.length * 13) % 20;
      return parseFloat((((seed - 10) / 10) * 0.9).toFixed(2));
    })
  );
}

const HEAT_COLORS = ["#1e3a5f", "#2563eb", "#60a5fa", "#e5e7eb", "#fca5a5", "#dc2626", "#7f1d1d"];
function corrColor(v: number) {
  const idx = Math.round(((v + 1) / 2) * 6);
  return HEAT_COLORS[Math.min(idx, 6)];
}

export default function FeatureAnalysisPage() {
  const [dateRange, setDateRange] = useState<"7d" | "30d" | "90d" | "custom">("30d");
  const { data: decisionsData } = useDecisionsData(dateRange);
  const [selectedFeature, setSelectedFeature] = useState<string>("credit_score");

  const decisions = decisionsData?.decisions ?? [];

  // Overlay histogram for selected feature by decision
  const overlayData = useMemo(() => {
    const bins = Array.from({ length: 10 }, (_, i) => ({ bin: i + 1, APPROVE: 0, REJECT: 0, MANUAL_REVIEW: 0 }));
    for (const d of decisions) {
      const raw = (d as unknown as Record<string, unknown>)[selectedFeature];
      if (typeof raw !== "number") continue;
      const pct = selectedFeature === "credit_score" ? (raw - 300) / 550 : Math.min(raw / 300000, 1);
      const idx = Math.min(Math.floor(pct * 10), 9);
      if (d.decision in bins[idx]) (bins[idx] as Record<string, number>)[d.decision]++;
    }
    return bins.map((b) => ({ ...b, bin: `${b.bin * 10}%` }));
  }, [decisions, selectedFeature]);

  const correlationMatrix = buildCorrelationMatrix(FEATURES);

  return (
    <DashboardShell role="data_scientist" userName="Jordan Kim" dateRange={dateRange} onDateRangeChange={setDateRange}>
      <div className="space-y-6">
        {/* Feature selector */}
        <div className="flex items-center gap-4">
          <label className="text-sm font-medium text-gray-700">Feature:</label>
          <select
            value={selectedFeature}
            onChange={(e) => setSelectedFeature(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none"
          >
            {FEATURES.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        </div>

        {/* Overlaid histogram */}
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <h3 className="font-bold text-gray-900 mb-4">
            {selectedFeature} Distribution by Decision Outcome
          </h3>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={overlayData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="bin" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip />
              <Legend />
              <Bar dataKey="APPROVE" name="Approve" fill="#22c55e" opacity={0.8} />
              <Bar dataKey="REJECT" name="Reject" fill="#ef4444" opacity={0.8} />
              <Bar dataKey="MANUAL_REVIEW" name="Manual Review" fill="#f59e0b" opacity={0.8} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Correlation heatmap */}
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <h3 className="font-bold text-gray-900 mb-4">Feature Correlation Heatmap</h3>
          <div className="overflow-x-auto">
            <table className="text-xs border-collapse">
              <thead>
                <tr>
                  <th className="w-28" />
                  {FEATURES.map((f) => (
                    <th key={f} className="px-1 py-1 font-mono font-normal text-gray-500 text-center" style={{ writingMode: "vertical-rl", minHeight: 80 }}>
                      {f}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {FEATURES.map((f1, i) => (
                  <tr key={f1}>
                    <td className="font-mono text-gray-500 pr-2 whitespace-nowrap">{f1}</td>
                    {correlationMatrix[i].map((v, j) => (
                      <td
                        key={j}
                        className="w-10 h-10 text-center font-semibold"
                        style={{ backgroundColor: corrColor(v), color: Math.abs(v) > 0.5 ? "#fff" : "#111" }}
                        title={`${f1} × ${FEATURES[j]}: ${v}`}
                      >
                        {v.toFixed(1)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center gap-2 mt-3 text-xs text-gray-500">
            <span>-1</span>
            <div className="flex flex-1 h-3 rounded overflow-hidden">
              {HEAT_COLORS.map((c, i) => <div key={i} className="flex-1" style={{ backgroundColor: c }} />)}
            </div>
            <span>+1</span>
          </div>
        </div>
      </div>
    </DashboardShell>
  );
}
