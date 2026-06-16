"use client";

import { useState } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AuditRecord {
  log_id: string;
  application_id: string;
  tenant_id: string;
  logged_at: string;
  decision_output: string;
  risk_score: number | null;
  fraud_score: number | null;
  reason_codes: string[] | null;
  policy_version: string | null;
  input_features: Record<string, unknown> | null;
}

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const API_URL = process.env.NEXT_PUBLIC_DECISION_API_URL ?? "http://localhost:8000";

function getToken() {
  return typeof window !== "undefined" ? (localStorage.getItem("decision_api_token") ?? "") : "";
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function RegulatorAuditRecordsPage() {
  const [applicationId, setApplicationId] = useState("");
  const [fromDate, setFromDate] = useState(
    new Date(Date.now() - 30 * 86_400_000).toISOString().slice(0, 10)
  );
  const [toDate, setToDate] = useState(new Date().toISOString().slice(0, 10));
  const [record, setRecord] = useState<AuditRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const search = async () => {
    if (!applicationId.trim()) {
      setError("Please enter an application ID.");
      return;
    }
    setLoading(true);
    setError(null);
    setRecord(null);
    try {
      const res = await fetch(
        `${API_URL}/v1/decisions/${encodeURIComponent(applicationId.trim())}/audit`,
        { headers: { Authorization: `Bearer ${getToken()}` } }
      );
      if (res.status === 404) {
        setError("No audit record found for this application ID.");
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setRecord(data);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  };

  const downloadJson = () => {
    if (!record) return;
    const blob = new Blob([JSON.stringify(record, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `audit_record_${record.application_id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const decisionColor = (d: string) => {
    if (d?.toUpperCase() === "APPROVE") return "text-green-700 bg-green-50 border-green-200";
    if (d?.toUpperCase() === "REJECT") return "text-red-700 bg-red-50 border-red-200";
    return "text-amber-700 bg-amber-50 border-amber-200";
  };

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="text-xl font-bold text-gray-900">Audit Records</h1>
        <p className="text-sm text-gray-500 mt-1">
          Read-only search of individual loan decision audit records.
        </p>
      </div>

      {/* Search form */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5 space-y-4">
        <div>
          <label className="block text-xs font-semibold text-gray-600 mb-1">Application ID</label>
          <input
            type="text"
            value={applicationId}
            onChange={(e) => setApplicationId(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && search()}
            placeholder="Enter UUID…"
            className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
          />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1">From Date</label>
            <input
              type="date"
              value={fromDate}
              onChange={(e) => setFromDate(e.target.value)}
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1">To Date</label>
            <input
              type="date"
              value={toDate}
              onChange={(e) => setToDate(e.target.value)}
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
            />
          </div>
        </div>
        <button
          onClick={search}
          disabled={loading}
          className="w-full rounded-lg bg-blue-600 text-white text-sm font-semibold py-2.5 hover:bg-blue-700 disabled:opacity-50 transition-colors"
        >
          {loading ? "Searching…" : "Search Audit Record"}
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Result */}
      {record && (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5 space-y-4">
          <div className="flex items-start justify-between">
            <div>
              <p className="text-xs text-gray-400">Application ID</p>
              <p className="font-mono text-sm text-gray-800">{record.application_id}</p>
            </div>
            <button
              onClick={downloadJson}
              className="text-xs font-medium text-blue-600 hover:underline border border-blue-200 rounded-lg px-3 py-1.5"
            >
              ⬇ Download JSON
            </button>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 text-sm">
            <div>
              <p className="text-xs text-gray-400">Decision</p>
              <span className={`inline-block mt-1 rounded-full border px-2.5 py-0.5 text-xs font-bold ${decisionColor(record.decision_output ?? "")}`}>
                {record.decision_output ?? "—"}
              </span>
            </div>
            <div>
              <p className="text-xs text-gray-400">Risk Score (PD)</p>
              <p className="font-semibold text-gray-800">{record.risk_score?.toFixed(4) ?? "—"}</p>
            </div>
            <div>
              <p className="text-xs text-gray-400">Fraud Score</p>
              <p className="font-semibold text-gray-800">{record.fraud_score?.toFixed(4) ?? "—"}</p>
            </div>
            <div>
              <p className="text-xs text-gray-400">Logged At</p>
              <p className="text-gray-700">{new Date(record.logged_at).toLocaleString()}</p>
            </div>
            <div>
              <p className="text-xs text-gray-400">Policy Version</p>
              <p className="text-gray-700">{record.policy_version ?? "—"}</p>
            </div>
            <div>
              <p className="text-xs text-gray-400">Reason Codes</p>
              <p className="text-gray-700">
                {Array.isArray(record.reason_codes) && record.reason_codes.length > 0
                  ? record.reason_codes.join(", ")
                  : "None"}
              </p>
            </div>
          </div>

          {record.input_features && (
            <details className="mt-2">
              <summary className="text-xs font-semibold text-gray-500 cursor-pointer select-none hover:text-gray-700">
                Feature Vector (click to expand)
              </summary>
              <pre className="mt-2 text-xs bg-gray-50 rounded-lg border border-gray-100 p-3 overflow-auto max-h-48 text-gray-700">
                {JSON.stringify(record.input_features, null, 2)}
              </pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
