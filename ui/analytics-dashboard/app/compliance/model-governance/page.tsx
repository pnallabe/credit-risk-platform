"use client";

import { useState } from "react";
import { DashboardShell, StatusBadge } from "@/components/DashboardShell";

interface ModelEntry {
  model_id: string;
  version: string;
  type: "credit_risk" | "fraud_detection";
  auc: number;
  ks: number;
  trained_at: string;
  deployed_at?: string;
  status: "CANDIDATE" | "DEPLOYED" | "ARCHIVED" | "CHALLENGER";
  champion: boolean;
}

const MOCK_MODELS: ModelEntry[] = [
  { model_id: "m-001", version: "1.3.0", type: "credit_risk", auc: 0.823, ks: 0.441, trained_at: "2025-01-15", deployed_at: "2025-01-20", status: "DEPLOYED", champion: true },
  { model_id: "m-002", version: "1.4.0", type: "credit_risk", auc: 0.837, ks: 0.458, trained_at: "2025-02-01", status: "CANDIDATE", champion: false },
  { model_id: "m-003", version: "1.2.1", type: "credit_risk", auc: 0.798, ks: 0.412, trained_at: "2024-11-10", deployed_at: "2024-11-15", status: "ARCHIVED", champion: false },
  { model_id: "m-004", version: "2.1.0", type: "fraud_detection", auc: 0.911, ks: 0.523, trained_at: "2025-01-28", deployed_at: "2025-02-03", status: "DEPLOYED", champion: true },
];

const STATUS_COLOR: Record<string, string> = {
  DEPLOYED: "bg-green-100 text-green-800",
  CANDIDATE: "bg-blue-100 text-blue-800",
  ARCHIVED: "bg-gray-100 text-gray-600",
  CHALLENGER: "bg-amber-100 text-amber-800",
};

export default function ModelGovernancePage() {
  const [dateRange, setDateRange] = useState<"7d" | "30d" | "90d" | "custom">("30d");
  const [models, setModels] = useState(MOCK_MODELS);
  const [approving, setApproving] = useState<string | null>(null);

  const promoteModel = async (modelId: string) => {
    if (!confirm(`Promote model ${modelId} to DEPLOYED (Champion)? Current champion will be archived.`)) return;
    setApproving(modelId);
    await new Promise((r) => setTimeout(r, 1200));
    setModels((prev) =>
      prev.map((m) => {
        if (m.model_id === modelId) return { ...m, status: "DEPLOYED" as const, champion: true, deployed_at: new Date().toISOString().split("T")[0] };
        if (m.status === "DEPLOYED" && m.type === prev.find((x) => x.model_id === modelId)?.type) return { ...m, status: "ARCHIVED" as const, champion: false };
        return m;
      })
    );
    setApproving(null);
  };

  return (
    <DashboardShell role="compliance" userName="Morgan Lee" dateRange={dateRange} onDateRangeChange={setDateRange}>
      <div className="space-y-6">
        <div>
          <h2 className="text-lg font-bold text-gray-900">Model Governance Registry</h2>
          <p className="text-sm text-gray-500">Champion/challenger framework — promote candidate models through approval workflow.</p>
        </div>

        <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">Model ID</th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">Version</th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">Type</th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">AUC</th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">KS</th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">Trained</th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">Status</th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {models.map((m) => (
                <tr key={m.model_id} className={`hover:bg-gray-50 ${m.champion ? "bg-green-50/30" : ""}`}>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs text-gray-700">{m.model_id}</span>
                      {m.champion && <span className="text-xs bg-yellow-100 text-yellow-800 px-1.5 py-0.5 rounded font-semibold">👑 Champion</span>}
                    </div>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-600">v{m.version}</td>
                  <td className="px-4 py-3 text-gray-700 capitalize">{m.type.replace("_", " ")}</td>
                  <td className="px-4 py-3">
                    <span className={`font-semibold ${m.auc >= 0.8 ? "text-green-700" : "text-amber-600"}`}>{m.auc.toFixed(3)}</span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`font-semibold ${m.ks >= 0.4 ? "text-green-700" : "text-amber-600"}`}>{m.ks.toFixed(3)}</span>
                  </td>
                  <td className="px-4 py-3 text-gray-600">{m.trained_at}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs font-semibold px-2 py-1 rounded-full ${STATUS_COLOR[m.status]}`}>{m.status}</span>
                  </td>
                  <td className="px-4 py-3">
                    {m.status === "CANDIDATE" && (
                      <button
                        onClick={() => promoteModel(m.model_id)}
                        disabled={approving === m.model_id}
                        className="text-xs bg-blue-600 hover:bg-blue-700 text-white px-3 py-1.5 rounded-lg font-medium disabled:opacity-50"
                      >
                        {approving === m.model_id ? "Promoting…" : "✅ Approve & Deploy"}
                      </button>
                    )}
                    {m.status === "ARCHIVED" && (
                      <span className="text-xs text-gray-400 italic">Archived</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Approval policy note */}
        <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 text-sm text-blue-800">
          <p className="font-semibold mb-1">SR 11-7 Model Governance Policy</p>
          <p>All model promotions require compliance officer approval. AUC ≥ 0.80 and KS ≥ 0.40 required for production. Challenger models run at 10% traffic split before champion promotion.</p>
        </div>
      </div>
    </DashboardShell>
  );
}
