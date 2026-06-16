"use client";

import { useEffect, useState } from "react";
import { DashboardShell } from "@/components/DashboardShell";

// ---------------------------------------------------------------------------
// Types — matches GET /v1/models response shape
// ---------------------------------------------------------------------------

interface ModelEntry {
  model_id: string;
  model_name: string;
  version: string;
  stage: string;
  auc?: string | number | null;
  ks?: string | number | null;
  trained_at?: number | string | null;
  deployed_at?: number | string | null;
  latest_governance_action?: string;
}

// ---------------------------------------------------------------------------
// API helper
// ---------------------------------------------------------------------------

const API_BASE = process.env.NEXT_PUBLIC_DECISION_API_URL ?? "";

async function apiFetch(path: string, opts?: RequestInit) {
  const token =
    typeof window !== "undefined" ? localStorage.getItem("decision_api_token") : "";
  return fetch(`${API_BASE}${path}`, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts?.headers ?? {}),
    },
  });
}

// ---------------------------------------------------------------------------
// Status colours (MLflow stages)
// ---------------------------------------------------------------------------

const STAGE_COLOR: Record<string, string> = {
  Production: "bg-green-100 text-green-800",
  Staging:    "bg-blue-100 text-blue-800",
  Archived:   "bg-gray-100 text-gray-600",
  None:       "bg-amber-100 text-amber-800",
};

function stageColor(stage: string) {
  return STAGE_COLOR[stage] ?? "bg-gray-100 text-gray-600";
}

// ---------------------------------------------------------------------------
// Skeleton row
// ---------------------------------------------------------------------------

function SkeletonRow() {
  return (
    <tr className="animate-pulse">
      {Array.from({ length: 8 }).map((_, i) => (
        <td key={i} className="px-4 py-3">
          <div className="h-3 bg-gray-200 rounded w-full" />
        </td>
      ))}
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Four-eyes Promote Dialog
// ---------------------------------------------------------------------------

function PromoteDialog({
  state,
  onConfirm,
  onClose,
  loading,
}: {
  state: { modelName: string; version: string };
  onConfirm: (approvedBy: string, notes: string) => void;
  onClose: () => void;
  loading: boolean;
}) {
  const [approvedBy, setApprovedBy] = useState("");
  const [notes, setNotes] = useState("");

  return (
    <div className="fixed inset-0 bg-black/30 z-50 flex items-center justify-center">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4">
        <h3 className="font-bold text-gray-900">
          Promote {state.modelName} v{state.version} → Production
        </h3>
        <p className="text-sm text-gray-500">
          SR 11-7 four-eyes: the approver email must differ from the submitter.
        </p>
        <div>
          <label className="block text-xs font-semibold text-gray-600 mb-1">
            Second Approver Email
          </label>
          <input
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
            placeholder="approver@company.com"
            value={approvedBy}
            onChange={(e) => setApprovedBy(e.target.value)}
          />
        </div>
        <div>
          <label className="block text-xs font-semibold text-gray-600 mb-1">Notes</label>
          <textarea
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 resize-none"
            rows={3}
            placeholder="Reason for promotion…"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </div>
        <div className="flex gap-3 justify-end">
          <button
            onClick={onClose}
            className="text-sm px-4 py-2 rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            onClick={() => onConfirm(approvedBy, notes)}
            disabled={!approvedBy || loading}
            className="text-sm px-4 py-2 rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 font-medium"
          >
            {loading ? "Promoting…" : "Confirm Promote"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ModelGovernancePage() {
  const [dateRange, setDateRange] = useState<"7d" | "30d" | "90d" | "custom">("30d");
  const [models, setModels] = useState<ModelEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [promoteDialog, setPromoteDialog] = useState<{ modelName: string; version: string } | null>(null);
  const [promoting, setPromoting] = useState(false);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);

  const showToast = (msg: string, ok = true) => {
    setToast({ msg, ok });
    setTimeout(() => setToast(null), 5000);
  };

  const fetchModels = async () => {
    setLoading(true);
    try {
      const res = await apiFetch("/v1/models");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setModels(json.models ?? []);
      setFetchError(null);
    } catch (e: unknown) {
      setFetchError(e instanceof Error ? e.message : "Failed to load models");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchModels();
  }, []);

  const handlePromoteConfirm = async (approvedBy: string, notes: string) => {
    if (!promoteDialog) return;
    setPromoting(true);
    try {
      const res = await apiFetch(
        `/v1/models/${promoteDialog.modelName}/${promoteDialog.version}/promote`,
        {
          method: "POST",
          body: JSON.stringify({ approved_by: approvedBy, notes }),
        }
      );
      if (res.status === 422) {
        const err = await res.json();
        throw new Error(err.detail ?? "Separation-of-duties violation");
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      showToast(
        `${promoteDialog.modelName} v${promoteDialog.version} promoted to Production`,
        true
      );
      setPromoteDialog(null);
      await fetchModels();
    } catch (e: unknown) {
      showToast(e instanceof Error ? e.message : "Promotion failed", false);
    } finally {
      setPromoting(false);
    }
  };

  const fmtTs = (ts?: number | string | null) => {
    if (!ts) return "—";
    const n = typeof ts === "number" ? ts : Date.parse(ts.toString());
    if (isNaN(n)) return String(ts);
    return new Date(n).toLocaleDateString();
  };

  const fmtNum = (v?: string | number | null) => {
    if (v == null) return "—";
    const n = Number(v);
    return isNaN(n) ? String(v) : n.toFixed(3);
  };

  return (
    <DashboardShell
      role="compliance"
      userName="Morgan Lee"
      dateRange={dateRange}
      onDateRangeChange={setDateRange}
    >
      {/* Toast */}
      {toast && (
        <div
          className={`fixed bottom-4 right-4 z-50 px-4 py-3 rounded-lg shadow-lg text-sm font-medium text-white ${
            toast.ok ? "bg-green-600" : "bg-red-600"
          }`}
        >
          {toast.msg}
        </div>
      )}

      {/* Promote dialog */}
      {promoteDialog && (
        <PromoteDialog
          state={promoteDialog}
          onConfirm={handlePromoteConfirm}
          onClose={() => setPromoteDialog(null)}
          loading={promoting}
        />
      )}

      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-gray-900">Model Governance Registry</h2>
            <p className="text-sm text-gray-500">
              Live model inventory from MLflow — promote Staging models with four-eyes approval.
            </p>
          </div>
          <button
            onClick={fetchModels}
            className="text-xs bg-gray-100 hover:bg-gray-200 text-gray-700 px-3 py-1.5 rounded-lg font-medium"
          >
            ↻ Refresh
          </button>
        </div>

        {fetchError && (
          <div className="bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-xl">
            {fetchError}
          </div>
        )}

        <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                {["Model", "Version", "Stage", "AUC", "KS", "Trained", "Last Action", "Actions"].map(
                  (h) => (
                    <th key={h} className="px-4 py-3 text-left font-semibold text-gray-600">
                      {h}
                    </th>
                  )
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {loading ? (
                Array.from({ length: 4 }).map((_, i) => <SkeletonRow key={i} />)
              ) : models.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-gray-400 text-sm">
                    No models found. Ensure MLflow is configured and models are registered.
                  </td>
                </tr>
              ) : (
                models.map((m) => (
                  <tr key={m.model_id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-mono text-xs text-gray-700">{m.model_name}</td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-600">v{m.version}</td>
                    <td className="px-4 py-3">
                      <span
                        className={`text-xs font-semibold px-2 py-1 rounded-full ${stageColor(m.stage)}`}
                      >
                        {m.stage}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`font-semibold ${
                          Number(m.auc) >= 0.8 ? "text-green-700" : "text-amber-600"
                        }`}
                      >
                        {fmtNum(m.auc)}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`font-semibold ${
                          Number(m.ks) >= 0.4 ? "text-green-700" : "text-amber-600"
                        }`}
                      >
                        {fmtNum(m.ks)}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-600">{fmtTs(m.trained_at)}</td>
                    <td className="px-4 py-3 text-xs text-gray-500">
                      {m.latest_governance_action ?? "—"}
                    </td>
                    <td className="px-4 py-3">
                      {m.stage === "Staging" && (
                        <button
                          onClick={() =>
                            setPromoteDialog({ modelName: m.model_name, version: m.version })
                          }
                          className="text-xs bg-blue-600 hover:bg-blue-700 text-white px-3 py-1.5 rounded-lg font-medium"
                        >
                          ✅ Promote
                        </button>
                      )}
                      {m.stage === "Archived" && (
                        <span className="text-xs text-gray-400 italic">Archived</span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Governance policy note */}
        <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 text-sm text-blue-800">
          <p className="font-semibold mb-1">SR 11-7 Model Governance Policy</p>
          <p>
            All model promotions require a second approver (four-eyes). AUC ≥ 0.80 and KS ≥ 0.40
            required for Production. Self-approval is blocked at the API level.
          </p>
        </div>
      </div>
    </DashboardShell>
  );
}
