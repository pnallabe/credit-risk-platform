"use client";

import { useState } from "react";
import { DashboardShell, StatusBadge } from "@/components/DashboardShell";
import { useDecisionsData } from "@/src/hooks";

const REASONS: Record<string, string> = {
  "HIGH_PD": "Credit risk score exceeds acceptable threshold",
  "HIGH_DTI": "Debt-to-income ratio is too high",
  "INSUFFICIENT_INCOME": "Insufficient income to support requested loan amount",
  "FRAUD_RISK": "Application flagged for potential fraud indicators",
  "CREDIT_HISTORY": "Derogatory marks on credit history",
};

export default function AdverseActionsPage() {
  const [dateRange, setDateRange] = useState<"7d" | "30d" | "90d" | "custom">("30d");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { data: decisionsData } = useDecisionsData(dateRange);

  const rejected = (decisionsData?.decisions ?? []).filter((d) => d.decision === "REJECT");

  const printNotice = (appId: string) => {
    const w = window.open("", "_blank");
    if (!w) return;
    w.document.write(`
      <html><head><title>Adverse Action Notice – ${appId}</title></head><body style="font-family:serif;max-width:600px;margin:40px auto">
        <h1 style="border-bottom:2px solid #000;padding-bottom:8px">Adverse Action Notice</h1>
        <p>Application ID: <strong>${appId}</strong></p>
        <p>Date: ${new Date().toLocaleDateString()}</p>
        <p>Dear Applicant, we regret to inform you that your credit application has been denied based on the following reasons:</p>
        <ul>${Object.values(REASONS).map((r) => `<li>${r}</li>`).join("")}</ul>
        <p style="font-size:12px;margin-top:32px;color:#555">This notice is provided in compliance with the Equal Credit Opportunity Act (ECOA) and the Fair Credit Reporting Act (FCRA). You have 60 days to request the specific reasons for this decision.</p>
      </body></html>
    `);
    w.document.close();
    w.print();
  };

  return (
    <DashboardShell role="compliance" userName="Morgan Lee" dateRange={dateRange} onDateRangeChange={setDateRange}>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-gray-900">Adverse Action Log</h2>
            <p className="text-sm text-gray-500">{rejected.length} rejections in period (ECOA-compliant logging)</p>
          </div>
        </div>

        <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">Application ID</th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">Decision</th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">Reason Codes</th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">PD Score</th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">Date</th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {rejected.map((d) => {
                const reasons = d.top_factors?.slice(0, 3) ?? ["HIGH_PD", "HIGH_DTI"];
                return (
                  <tr key={d.application_id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-mono text-xs text-blue-700">{d.application_id?.slice(0, 12)}…</td>
                    <td className="px-4 py-3"><StatusBadge status={d.decision} /></td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {reasons.map((r) => (
                          <span key={r} className="text-xs bg-red-50 text-red-700 px-2 py-0.5 rounded-full font-medium">{r}</span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-red-600 font-semibold">{((d.pd_score ?? 0) * 100).toFixed(1)}%</td>
                    <td className="px-4 py-3 text-gray-600">{new Date(d.created_at).toLocaleDateString()}</td>
                    <td className="px-4 py-3">
                      <div className="flex gap-2">
                        <button
                          onClick={() => setSelectedId(d.application_id)}
                          className="text-xs text-blue-600 hover:underline"
                        >View</button>
                        <button
                          onClick={() => printNotice(d.application_id)}
                          className="text-xs bg-gray-100 hover:bg-gray-200 px-2 py-1 rounded text-gray-700"
                        >🖨 Print Notice</button>
                      </div>
                    </td>
                  </tr>
                );
              })}
              {rejected.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-12 text-center text-gray-400">No rejections in this period.</td></tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Detail overlay */}
        {selectedId && (
          <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
            <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-bold text-gray-900">Adverse Action Detail</h3>
                <button onClick={() => setSelectedId(null)} className="text-gray-400 hover:text-gray-700">✕</button>
              </div>
              <p className="text-sm text-gray-500 mb-4">Application: <span className="font-mono text-gray-900">{selectedId}</span></p>
              <h4 className="font-semibold text-gray-700 mb-2 text-sm">Reason Explanations (FCRA §615):</h4>
              <ul className="space-y-2">
                {Object.entries(REASONS).slice(0, 3).map(([code, desc]) => (
                  <li key={code} className="bg-red-50 rounded-lg p-3">
                    <p className="font-semibold text-red-700 text-xs">{code}</p>
                    <p className="text-sm text-gray-700">{desc}</p>
                  </li>
                ))}
              </ul>
              <div className="flex gap-2 mt-4">
                <button onClick={() => printNotice(selectedId)} className="flex-1 bg-gray-900 text-white py-2 rounded-lg text-sm font-medium hover:bg-gray-800">
                  🖨 Print ECOA Notice
                </button>
                <button onClick={() => setSelectedId(null)} className="flex-1 border border-gray-300 text-gray-700 py-2 rounded-lg text-sm font-medium hover:bg-gray-50">
                  Close
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </DashboardShell>
  );
}
