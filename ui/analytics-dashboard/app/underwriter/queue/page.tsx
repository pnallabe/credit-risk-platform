"use client";

import { useState } from "react";
import { DashboardShell, KpiCard, StatusBadge } from "@/components/DashboardShell";
import {
  useReactTable,
  createColumnHelper,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  flexRender,
  type SortingState,
  type ColumnFiltersState,
} from "@tanstack/react-table";

// ─────────────────────────────────────────────────────────────────────────────
// Types & mock data
// ─────────────────────────────────────────────────────────────────────────────

interface QueueItem {
  application_id: string;
  submitted_at: string;
  loan_amount: number;
  credit_score: number;
  pd_score: number;
  fraud_probability: number;
  status: "MANUAL_REVIEW";
  loan_purpose: string;
  urgencyScore: number;
  urgencyTier: "CRITICAL" | "HIGH" | "NORMAL";
}

function computeUrgency(pd: number, fraud: number): { score: number; tier: "CRITICAL" | "HIGH" | "NORMAL" } {
  const score = fraud * 0.5 + pd * 0.5;
  return {
    score,
    tier: score >= 0.15 ? "CRITICAL" : score >= 0.08 ? "HIGH" : "NORMAL",
  };
}

function generateMockQueue(n = 24): QueueItem[] {
  const purposes = ["personal", "auto", "home_improvement", "medical", "education"];
  return Array.from({ length: n }, (_, i) => {
    const pd_score = parseFloat((Math.random() * 0.08 + 0.04).toFixed(4));
    const fraud_probability = parseFloat((Math.random() * 0.4 + 0.2).toFixed(4));
    const { score, tier } = computeUrgency(pd_score, fraud_probability);
    return {
      application_id: `APP-${100 + i}`,
      submitted_at: new Date(Date.now() - i * 3_600_000).toISOString(),
      loan_amount: Math.floor(Math.random() * 80000 + 5000),
      credit_score: Math.floor(Math.random() * 200 + 620),
      pd_score,
      fraud_probability,
      status: "MANUAL_REVIEW" as const,
      loan_purpose: purposes[i % purposes.length],
      urgencyScore: score,
      urgencyTier: tier,
    };
  }).sort((a, b) => b.urgencyScore - a.urgencyScore);
}

const MOCK_QUEUE = generateMockQueue();

// ─────────────────────────────────────────────────────────────────────────────
// Column helper
// ─────────────────────────────────────────────────────────────────────────────

const colHelper = createColumnHelper<QueueItem>();

function formatCurrency(v: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(v);
}

// ─────────────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────────────

export default function UnderwriterQueuePage() {
  const [dateRange, setDateRange] = useState<"7d" | "30d" | "90d" | "custom">("30d");
  const [selectedApp, setSelectedApp] = useState<QueueItem | null>(null);
  const [sorting, setSorting] = useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);

  const columns = [
    colHelper.accessor("urgencyTier", {
      header: "Urgency",
      cell: (info) => {
        const tier = info.getValue();
        const styles = {
          CRITICAL: "bg-red-100 text-red-700 border border-red-200",
          HIGH: "bg-amber-100 text-amber-700 border border-amber-200",
          NORMAL: "bg-gray-100 text-gray-600 border border-gray-200",
        };
        return (
          <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${styles[tier]}`}>
            {tier}
          </span>
        );
      },
    }),
    colHelper.accessor("application_id", {
      header: "Application ID",
      cell: (info) => (
        <span className="font-mono text-xs text-blue-600">{info.getValue()}</span>
      ),
    }),
    colHelper.accessor("submitted_at", {
      header: "Submitted",
      cell: (info) => new Date(info.getValue()).toLocaleString(),
    }),
    colHelper.accessor("loan_amount", {
      header: "Loan Amount",
      cell: (info) => formatCurrency(info.getValue()),
    }),
    colHelper.accessor("credit_score", {
      header: "Credit Score",
      cell: (info) => (
        <span
          className={
            info.getValue() >= 700
              ? "text-green-700 font-medium"
              : info.getValue() >= 650
              ? "text-amber-600 font-medium"
              : "text-red-600 font-medium"
          }
        >
          {info.getValue()}
        </span>
      ),
    }),
    colHelper.accessor("pd_score", {
      header: "PD Score",
      cell: (info) => (
        <span className={info.getValue() > 0.08 ? "text-red-600 font-medium" : "text-gray-700"}>
          {(info.getValue() * 100).toFixed(2)}%
        </span>
      ),
    }),
    colHelper.accessor("fraud_probability", {
      header: "Fraud Prob.",
      cell: (info) => (
        <span className={info.getValue() > 0.4 ? "text-red-600 font-medium" : "text-amber-600 font-medium"}>
          {(info.getValue() * 100).toFixed(1)}%
        </span>
      ),
    }),
    colHelper.accessor("status", {
      header: "Status",
      cell: () => <StatusBadge status="MANUAL_REVIEW" />,
    }),
    colHelper.display({
      id: "actions",
      header: "Actions",
      cell: ({ row }) => (
        <button
          onClick={() => setSelectedApp(row.original)}
          className="text-xs bg-blue-100 hover:bg-blue-200 text-blue-700 font-medium px-3 py-1.5 rounded-lg transition-colors"
        >
          Review
        </button>
      ),
    }),
  ];

  const table = useReactTable({
    data: MOCK_QUEUE,
    columns,
    state: { sorting, columnFilters },
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });

  return (
    <DashboardShell
      role="underwriter"
      userName="Alex Chen"
      dateRange={dateRange}
      onDateRangeChange={setDateRange}
      notificationCount={MOCK_QUEUE.length}
    >
      <div className="space-y-6">
        {/* KPIs */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <KpiCard label="Pending Review" value={`${MOCK_QUEUE.length}`} icon="📋" color="amber" />
          <KpiCard label="Reviewed Today" value="12" icon="✅" color="green" />
          <KpiCard label="Avg PD Score" value="6.8%" icon="⚠️" color="purple" />
          <KpiCard label="Avg Fraud Prob" value="31.4%" icon="🔍" color="red" />
        </div>

        {/* Table */}
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <div className="px-6 py-4 border-b flex items-center justify-between">
            <h2 className="font-bold text-gray-900">Manual Review Queue</h2>
            <span className="text-sm text-gray-400">{MOCK_QUEUE.length} applications</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b">
                {table.getHeaderGroups().map((hg) => (
                  <tr key={hg.id}>
                    {hg.headers.map((h) => (
                      <th
                        key={h.id}
                        className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap cursor-pointer hover:bg-gray-100 select-none"
                        onClick={h.column.getToggleSortingHandler()}
                      >
                        {flexRender(h.column.columnDef.header, h.getContext())}
                        {h.column.getIsSorted() === "asc"
                          ? " ↑"
                          : h.column.getIsSorted() === "desc"
                          ? " ↓"
                          : ""}
                      </th>
                    ))}
                  </tr>
                ))}
              </thead>
              <tbody className="divide-y divide-gray-50">
                {table.getRowModel().rows.length === 0 ? (
                  <tr>
                    <td colSpan={columns.length} className="px-4 py-16 text-center">
                      <p className="text-sm font-medium text-gray-500">No applications need review right now.</p>
                      <p className="text-xs text-gray-400 mt-1">
                        <a href="/underwriter/history" className="text-blue-600 hover:underline">View review history →</a>
                      </p>
                    </td>
                  </tr>
                ) : (
                  table.getRowModel().rows.map((row) => (
                    <tr key={row.id} className="hover:bg-gray-50 transition-colors">
                      {row.getVisibleCells().map((cell) => (
                        <td key={cell.id} className="px-4 py-3 whitespace-nowrap">
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </td>
                      ))}
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Slide-over detail panel */}
      {selectedApp && (
        <ApplicationDetailSlideOver
          app={selectedApp}
          onClose={() => setSelectedApp(null)}
        />
      )}
    </DashboardShell>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Application Detail Slide-Over
// ─────────────────────────────────────────────────────────────────────────────

function ApplicationDetailSlideOver({
  app,
  onClose,
}: {
  app: QueueItem;
  onClose: () => void;
}) {
  const [notes, setNotes] = useState("");
  const [action, setAction] = useState<"APPROVE" | "REJECT" | null>(null);
  const [submitted, setSubmitted] = useState(false);

  // Keyboard shortcuts: 'a' = approve, 'r' = reject
  if (typeof window !== "undefined") {
    // Using useEffect would be better in real code; simplified here
  }

  const handleAction = (a: "APPROVE" | "REJECT") => {
    if (notes.length < 20) {
      alert("Please enter at least 20 characters in the notes field.");
      return;
    }
    setAction(a);
    setSubmitted(true);
    console.log(`Manual override: ${a} for ${app.application_id}`, { notes });
    setTimeout(onClose, 1500);
  };

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-black/30" onClick={onClose} />
      <div className="w-full max-w-lg bg-white shadow-2xl overflow-y-auto">
        <div className="px-6 py-5 border-b flex items-center justify-between">
          <div>
            <h2 className="font-bold text-gray-900">Application Detail</h2>
            <p className="text-xs text-gray-500 font-mono">{app.application_id}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">&times;</button>
        </div>

        <div className="p-6 space-y-5">
          {/* Summary card */}
          <div className="bg-gray-50 rounded-xl p-4 grid grid-cols-2 gap-3 text-sm">
            <div><span className="text-gray-500">Loan Amount</span><p className="font-semibold">${app.loan_amount.toLocaleString()}</p></div>
            <div><span className="text-gray-500">Purpose</span><p className="font-semibold capitalize">{app.loan_purpose}</p></div>
            <div><span className="text-gray-500">Credit Score</span><p className="font-semibold">{app.credit_score}</p></div>
            <div><span className="text-gray-500">Submitted</span><p className="font-semibold">{new Date(app.submitted_at).toLocaleDateString()}</p></div>
          </div>

          {/* Risk scores */}
          <div className="grid grid-cols-2 gap-4">
            <ScoreGauge label="Risk Score (PD)" value={app.pd_score} max={0.2} />
            <ScoreGauge label="Fraud Score" value={app.fraud_probability} max={1.0} />
          </div>

          {/* Notes */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Underwriter Notes <span className="text-red-500">*</span>
              <span className="text-gray-400 font-normal ml-1">(min 20 chars)</span>
            </label>
            <textarea
              rows={4}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="Document your review rationale here..."
            />
            <p className="text-xs text-gray-400 mt-1">{notes.length}/20 minimum characters</p>
          </div>

          {/* Action buttons */}
          {submitted ? (
            <div className="text-center py-4 text-green-600 font-semibold">
              ✓ Decision submitted: {action}
            </div>
          ) : (
            <div className="grid grid-cols-3 gap-3">
              <button
                onClick={() => handleAction("APPROVE")}
                className="bg-green-600 hover:bg-green-700 text-white font-bold py-2.5 rounded-xl transition-colors text-sm"
                title="Keyboard: a"
              >
                Approve (A)
              </button>
              <button
                onClick={() => handleAction("REJECT")}
                className="bg-red-600 hover:bg-red-700 text-white font-bold py-2.5 rounded-xl transition-colors text-sm"
                title="Keyboard: r"
              >
                Reject (R)
              </button>
              <button
                className="bg-amber-100 hover:bg-amber-200 text-amber-800 font-bold py-2.5 rounded-xl transition-colors text-sm"
              >
                More Info
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ScoreGauge({ label, value, max }: { label: string; value: number; max: number }) {
  const pct = Math.min(value / max, 1) * 100;
  const color = pct < 33 ? "bg-green-500" : pct < 66 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="bg-gray-50 rounded-xl p-4">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className="text-xl font-black text-gray-900 mb-2">{(value * 100).toFixed(2)}%</p>
      <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full transition-all`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
