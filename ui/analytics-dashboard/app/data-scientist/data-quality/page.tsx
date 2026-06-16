"use client";

import { useState } from "react";
import { DashboardShell, KpiCard } from "@/components/DashboardShell";

interface ColumnQuality {
  column: string;
  dtype: string;
  null_pct: number;
  outlier_pct: number;
  unique_count: number;
  enum_valid: boolean | null; // null if not enum
  status: "ok" | "warning" | "error";
}

const MOCK_QUALITY: ColumnQuality[] = [
  { column: "annual_income", dtype: "float64", null_pct: 0.2, outlier_pct: 1.4, unique_count: 8412, enum_valid: null, status: "ok" },
  { column: "credit_score", dtype: "int64", null_pct: 0.0, outlier_pct: 0.0, unique_count: 394, enum_valid: null, status: "ok" },
  { column: "dti_ratio", dtype: "float64", null_pct: 0.8, outlier_pct: 3.2, unique_count: 9821, enum_valid: null, status: "warning" },
  { column: "loan_amount", dtype: "float64", null_pct: 0.0, outlier_pct: 0.9, unique_count: 7233, enum_valid: null, status: "ok" },
  { column: "employment_status", dtype: "object", null_pct: 4.1, outlier_pct: 0.0, unique_count: 6, enum_valid: false, status: "error" },
  { column: "loan_purpose", dtype: "object", null_pct: 0.0, outlier_pct: 0.0, unique_count: 8, enum_valid: true, status: "ok" },
  { column: "home_ownership", dtype: "object", null_pct: 0.1, outlier_pct: 0.0, unique_count: 4, enum_valid: true, status: "ok" },
  { column: "derogatory_marks", dtype: "int64", null_pct: 1.8, outlier_pct: 2.1, unique_count: 12, enum_valid: null, status: "warning" },
];

const STATUS_STYLE: Record<string, string> = {
  ok: "bg-green-100 text-green-800",
  warning: "bg-amber-100 text-amber-800",
  error: "bg-red-100 text-red-800",
};

export default function DataQualityPage() {
  const [dateRange, setDateRange] = useState<"7d" | "30d" | "90d" | "custom">("30d");
  const [runDate] = useState(() => new Date().toLocaleString());

  const okCount = MOCK_QUALITY.filter((c) => c.status === "ok").length;
  const warnCount = MOCK_QUALITY.filter((c) => c.status === "warning").length;
  const errCount = MOCK_QUALITY.filter((c) => c.status === "error").length;
  const avgNullPct = (MOCK_QUALITY.reduce((a, b) => a + b.null_pct, 0) / MOCK_QUALITY.length).toFixed(1);

  return (
    <DashboardShell role="data_scientist" userName="Jordan Kim" dateRange={dateRange} onDateRangeChange={setDateRange}>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-gray-900">Data Quality Report</h2>
            <p className="text-sm text-gray-500">Schema validation • Outlier detection • Null scanning — {runDate}</p>
          </div>
          <button
            onClick={() => alert("Re-running data quality scan…")}
            className="text-sm bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg font-medium"
          >
            ↻ Re-run Scan
          </button>
        </div>

        {/* KPIs */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <KpiCard label="Healthy Columns" value={`${okCount}/${MOCK_QUALITY.length}`} icon="✅" color="green" />
          <KpiCard label="Warnings" value={warnCount.toString()} icon="⚠️" color={warnCount > 0 ? "amber" : "green"} />
          <KpiCard label="Errors" value={errCount.toString()} icon="🚨" color={errCount > 0 ? "red" : "green"} />
          <KpiCard label="Avg Null %" value={`${avgNullPct}%`} icon="🕳" color={parseFloat(avgNullPct) > 2 ? "amber" : "green"} />
        </div>

        {/* Quality table */}
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">Column</th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">Type</th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">Null %</th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">Outlier %</th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">Unique</th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">Enum Valid</th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {MOCK_QUALITY.map((c) => (
                <tr key={c.column} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-mono text-xs text-gray-700">{c.column}</td>
                  <td className="px-4 py-3">
                    <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded font-mono">{c.dtype}</span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className="w-16 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                        <div className={`h-full rounded-full ${c.null_pct > 3 ? "bg-red-500" : c.null_pct > 1 ? "bg-amber-400" : "bg-green-500"}`} style={{ width: `${Math.min(c.null_pct / 10, 1) * 100}%` }} />
                      </div>
                      <span className={c.null_pct > 3 ? "text-red-600 font-semibold" : "text-gray-600"}>{c.null_pct}%</span>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span className={c.outlier_pct > 2 ? "text-amber-600 font-semibold" : "text-gray-600"}>{c.outlier_pct}%</span>
                  </td>
                  <td className="px-4 py-3 text-gray-600">{c.unique_count.toLocaleString()}</td>
                  <td className="px-4 py-3">
                    {c.enum_valid === null ? <span className="text-gray-300">—</span> : c.enum_valid ? <span className="text-green-600">✓</span> : <span className="text-red-600 font-bold">✗ Invalid values</span>}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`text-xs font-semibold px-2 py-1 rounded-full capitalize ${STATUS_STYLE[c.status]}`}>{c.status}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Errors section */}
        {errCount > 0 && (
          <div className="bg-red-50 border border-red-200 rounded-xl p-4">
            <p className="font-semibold text-red-800 mb-2">🚨 Data Quality Errors Detected</p>
            {MOCK_QUALITY.filter((c) => c.status === "error").map((c) => (
              <p key={c.column} className="text-sm text-red-700">
                <strong className="font-mono">{c.column}</strong>: Enum validation failed — unexpected categorical values in production data.
              </p>
            ))}
          </div>
        )}
      </div>
    </DashboardShell>
  );
}
