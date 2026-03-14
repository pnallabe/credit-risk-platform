"use client";

import { useState, useMemo, useCallback } from "react";
import { DashboardShell, StatusBadge } from "@/components/DashboardShell";
import { useDecisionsData } from "@/src/hooks";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";

interface Decision {
  application_id: string;
  decision: string;
  created_at: string;
  loan_amount: number;
  pd_score: number;
  reviewer?: string;
  review_complete_at?: string;
}

export default function UnderwriterHistoryPage() {
  const [dateRange, setDateRange] = useState<"7d" | "30d" | "90d" | "custom">("30d");
  const [sorting, setSorting] = useState<SortingState>([{ id: "created_at", desc: true }]);
  const [globalFilter, setGlobalFilter] = useState("");
  const { data: decisionsData } = useDecisionsData(dateRange);

  // Filter to only reviewed (non-PENDING) decisions
  const history: Decision[] = useMemo(
    () => (decisionsData?.decisions ?? []).filter((d) => d.decision !== "PENDING"),
    [decisionsData]
  );

  const columns = useMemo<ColumnDef<Decision>[]>(
    () => [
      {
        accessorKey: "application_id",
        header: "Application ID",
        cell: ({ getValue }) => (
          <span className="font-mono text-xs text-blue-700">{(getValue() as string).slice(0, 12)}…</span>
        ),
      },
      {
        accessorKey: "decision",
        header: "Decision",
        cell: ({ getValue }) => <StatusBadge status={getValue() as string} />,
      },
      {
        accessorKey: "loan_amount",
        header: "Loan Amount",
        cell: ({ getValue }) =>
          new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(
            getValue() as number
          ),
      },
      {
        accessorKey: "pd_score",
        header: "PD Score",
        cell: ({ getValue }) => (
          <span className={(getValue() as number) > 0.5 ? "text-red-600 font-semibold" : "text-green-600 font-semibold"}>
            {((getValue() as number) * 100).toFixed(1)}%
          </span>
        ),
      },
      {
        accessorKey: "reviewer",
        header: "Reviewer",
        cell: ({ getValue }) => getValue() ?? <span className="text-gray-400 italic">—</span>,
      },
      {
        accessorKey: "review_complete_at",
        header: "Reviewed At",
        cell: ({ getValue }) =>
          getValue() ? new Date(getValue() as string).toLocaleString() : "—",
      },
      {
        accessorKey: "created_at",
        header: "Submitted At",
        cell: ({ getValue }) => new Date(getValue() as string).toLocaleDateString(),
      },
    ],
    []
  );

  const table = useReactTable({
    data: history,
    columns,
    state: { sorting, globalFilter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: 25 } },
  });

  const exportCsv = useCallback(() => {
    const rows = table.getFilteredRowModel().rows;
    const headers = ["application_id", "decision", "loan_amount", "pd_score", "reviewer", "review_complete_at", "created_at"];
    const csvRows = [
      headers.join(","),
      ...rows.map((r) => headers.map((h) => JSON.stringify((r.original as Record<string, unknown>)[h] ?? "")).join(",")),
    ];
    const blob = new Blob([csvRows.join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `underwriter-history-${dateRange}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [table, dateRange]);

  return (
    <DashboardShell role="underwriter" userName="Alex Chen" dateRange={dateRange} onDateRangeChange={setDateRange}>
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-gray-900">Decision History</h2>
            <p className="text-sm text-gray-500">{history.length} reviewed applications</p>
          </div>
          <button
            onClick={exportCsv}
            className="flex items-center gap-2 bg-white border border-gray-300 hover:bg-gray-50 text-gray-700 text-sm font-medium px-4 py-2 rounded-lg transition-colors"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" /></svg>
            Export CSV
          </button>
        </div>

        {/* Search */}
        <input
          type="search"
          placeholder="Search by application ID, reviewer…"
          value={globalFilter}
          onChange={(e) => setGlobalFilter(e.target.value)}
          className="w-full max-w-md border border-gray-300 rounded-lg px-4 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none"
        />

        {/* Table */}
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b">
                {table.getHeaderGroups().map((hg) => (
                  <tr key={hg.id}>
                    {hg.headers.map((h) => (
                      <th
                        key={h.id}
                        className="px-4 py-3 text-left font-semibold text-gray-600 cursor-pointer select-none hover:text-gray-900"
                        onClick={h.column.getToggleSortingHandler()}
                      >
                        <span className="flex items-center gap-1">
                          {flexRender(h.column.columnDef.header, h.getContext())}
                          {{ asc: " ↑", desc: " ↓" }[h.column.getIsSorted() as string] ?? ""}
                        </span>
                      </th>
                    ))}
                  </tr>
                ))}
              </thead>
              <tbody className="divide-y divide-gray-50">
                {table.getRowModel().rows.map((row) => (
                  <tr key={row.id} className="hover:bg-gray-50">
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id} className="px-4 py-3 text-gray-700">
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                ))}
                {table.getRowModel().rows.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-4 py-12 text-center text-gray-400">No records found.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          {/* Pagination */}
          <div className="px-4 py-3 border-t flex items-center justify-between text-sm text-gray-600">
            <span>Page {table.getState().pagination.pageIndex + 1} of {table.getPageCount()}</span>
            <div className="flex gap-2">
              <button onClick={() => table.previousPage()} disabled={!table.getCanPreviousPage()} className="px-3 py-1 border rounded disabled:opacity-40 hover:bg-gray-50">←</button>
              <button onClick={() => table.nextPage()} disabled={!table.getCanNextPage()} className="px-3 py-1 border rounded disabled:opacity-40 hover:bg-gray-50">→</button>
            </div>
          </div>
        </div>
      </div>
    </DashboardShell>
  );
}
