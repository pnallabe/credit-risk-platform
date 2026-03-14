"use client";

import { useState } from "react";
import { DashboardShell, StatusBadge } from "@/components/DashboardShell";

interface AuditRecord {
  application_id: string;
  decision: string;
  model_version: string;
  features: Record<string, number>;
  shap_values: Record<string, number>;
  created_at: string;
}

export default function AuditExplorerPage() {
  const [dateRange, setDateRange] = useState<"7d" | "30d" | "90d" | "custom">("30d");
  const [searchId, setSearchId] = useState("");
  const [loading, setLoading] = useState(false);
  const [record, setRecord] = useState<AuditRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [replaying, setReplaying] = useState(false);
  const [replayResult, setReplayResult] = useState<{ decision: string; pd_score: number } | null>(null);

  const search = async () => {
    if (!searchId.trim()) return;
    setLoading(true);
    setError(null);
    setRecord(null);
    setReplayResult(null);
    try {
      const res = await fetch(`/api/v1/decisions/${searchId.trim()}/audit`);
      if (!res.ok) throw new Error(`Not found (${res.status})`);
      const data = await res.json();
      setRecord(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const replayDecision = async () => {
    if (!record) return;
    setReplaying(true);
    try {
      const res = await fetch("/api/v1/decisions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(record.features),
      });
      const data = await res.json();
      setReplayResult({ decision: data.decision, pd_score: data.pd_score });
    } finally {
      setReplaying(false);
    }
  };

  return (
    <DashboardShell role="compliance" userName="Morgan Lee" dateRange={dateRange} onDateRangeChange={setDateRange}>
      <div className="space-y-6">
        <div>
          <h2 className="text-lg font-bold text-gray-900">Audit Explorer</h2>
          <p className="text-sm text-gray-500">Search any application by ID to view full audit trail and replay the decision.</p>
        </div>

        {/* Search bar */}
        <div className="flex gap-3 max-w-xl">
          <input
            type="text"
            value={searchId}
            onChange={(e) => setSearchId(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && search()}
            placeholder="Enter Application UUID…"
            className="flex-1 border border-gray-300 rounded-lg px-4 py-2.5 text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none font-mono"
          />
          <button
            onClick={search}
            disabled={loading}
            className="bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-5 py-2.5 rounded-lg transition-colors disabled:opacity-50"
          >
            {loading ? "…" : "Search"}
          </button>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">{error}</div>
        )}

        {record && (
          <div className="space-y-4">
            {/* Header card */}
            <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-xs text-gray-500 mb-1">Application ID</p>
                  <p className="font-mono text-sm text-gray-900 mb-3">{record.application_id}</p>
                  <div className="flex items-center gap-3">
                    <StatusBadge status={record.decision} />
                    <span className="text-xs text-gray-500">Model v{record.model_version}</span>
                    <span className="text-xs text-gray-500">{new Date(record.created_at).toLocaleString()}</span>
                  </div>
                </div>
                <button
                  onClick={replayDecision}
                  disabled={replaying}
                  className="bg-amber-500 hover:bg-amber-600 text-white text-sm font-medium px-4 py-2 rounded-lg flex items-center gap-2"
                >
                  <span>▶</span> {replaying ? "Replaying…" : "Replay Decision"}
                </button>
              </div>

              {replayResult && (
                <div className="mt-4 bg-blue-50 border border-blue-200 rounded-lg p-4">
                  <p className="text-xs font-semibold text-blue-700 mb-1">Replay Result (current model)</p>
                  <div className="flex items-center gap-3">
                    <StatusBadge status={replayResult.decision} />
                    <span className="text-sm text-gray-700">PD: {(replayResult.pd_score * 100).toFixed(2)}%</span>
                    {replayResult.decision !== record.decision && (
                      <span className="text-xs bg-red-100 text-red-700 px-2 py-0.5 rounded-full font-semibold">⚠ Decision Changed!</span>
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* Feature values */}
            <div className="grid lg:grid-cols-2 gap-4">
              <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
                <h3 className="font-semibold text-gray-900 mb-3">Input Features</h3>
                <dl className="space-y-2">
                  {Object.entries(record.features).map(([k, v]) => (
                    <div key={k} className="flex justify-between text-sm">
                      <dt className="font-mono text-gray-500">{k}</dt>
                      <dd className="font-semibold text-gray-800">{typeof v === "number" ? v.toLocaleString() : String(v)}</dd>
                    </div>
                  ))}
                </dl>
              </div>

              <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
                <h3 className="font-semibold text-gray-900 mb-3">SHAP Shapley Values</h3>
                <dl className="space-y-2">
                  {Object.entries(record.shap_values)
                    .sort(([, a], [, b]) => Math.abs(b) - Math.abs(a))
                    .map(([k, v]) => (
                      <div key={k} className="flex justify-between items-center text-sm gap-2">
                        <dt className="font-mono text-gray-500 truncate">{k}</dt>
                        <dd className="flex items-center gap-2">
                          <div className="w-20 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                            <div
                              className={`h-full rounded-full ${v > 0 ? "bg-red-500" : "bg-green-500"}`}
                              style={{ width: `${Math.min(Math.abs(v) / 0.3, 1) * 100}%`, marginLeft: v < 0 ? undefined : 0 }}
                            />
                          </div>
                          <span className={`font-semibold ${v > 0 ? "text-red-600" : "text-green-600"}`}>{v > 0 ? "+" : ""}{v.toFixed(4)}</span>
                        </dd>
                      </div>
                    ))}
                </dl>
              </div>
            </div>
          </div>
        )}
      </div>
    </DashboardShell>
  );
}
