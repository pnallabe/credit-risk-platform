"use client";

import { useEffect, useState } from "react";
import { DashboardShell, KpiCard } from "@/components/DashboardShell";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ComplianceHealth {
  overall_score: number;
  dimension_scores: Record<string, number>;
  failing_dimensions: string[];
  status: "GREEN" | "YELLOW" | "RED";
  computed_at: string;
}

// ---------------------------------------------------------------------------
// Simple useSWR-like hook with 60-second refresh
// ---------------------------------------------------------------------------

function useComplianceHealth() {
  const [data, setData] = useState<ComplianceHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    try {
      const token = (typeof window !== "undefined" && localStorage.getItem("decision_api_token")) || "";
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_DECISION_API_URL ?? ""}/v1/compliance/health`,
        { headers: token ? { Authorization: `Bearer ${token}` } : {} }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setData(json);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 60_000);
    return () => clearInterval(interval);
  }, []);

  return { data, loading, error, mutate: fetchData };
}

// ---------------------------------------------------------------------------
// Score-colour helpers
// ---------------------------------------------------------------------------

function scoreColor(score: number): "green" | "amber" | "red" {
  if (score >= 80) return "green";
  if (score >= 60) return "amber";
  return "red";
}

function ringStroke(score: number): string {
  if (score >= 80) return "#22c55e";
  if (score >= 60) return "#f59e0b";
  return "#ef4444";
}

// ---------------------------------------------------------------------------
// Skeleton loader
// ---------------------------------------------------------------------------

function SkeletonCard() {
  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 animate-pulse">
      <div className="h-4 bg-gray-200 rounded w-1/2 mb-2" />
      <div className="h-8 bg-gray-300 rounded w-3/4" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Toast
// ---------------------------------------------------------------------------

interface Toast {
  id: number;
  msg: string;
  type: "success" | "error";
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ComplianceCommandCenterPage() {
  const [dateRange, setDateRange] = useState<"7d" | "30d" | "90d" | "custom">("30d");
  const { data: health, loading, error } = useComplianceHealth();
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [generating, setGenerating] = useState(false);

  const addToast = (msg: string, type: "success" | "error" = "success") => {
    const id = Date.now();
    setToasts((prev) => [...prev, { id, msg, type }]);
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 5000);
  };

  const handleGeneratePackage = async () => {
    setGenerating(true);
    try {
      const token = (typeof window !== "undefined" && localStorage.getItem("decision_api_token")) || "";
      const today = new Date().toISOString().split("T")[0];
      const quarterStart = today.slice(0, 7) + "-01";
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_DECISION_API_URL ?? ""}/v1/audit/generate-package`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({ from_date: quarterStart, to_date: today, format: "json" }),
        }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      addToast(`Audit package generated: ${json.packet_id ?? "OK"}`, "success");
    } catch (e: unknown) {
      addToast(e instanceof Error ? e.message : "Failed to generate package", "error");
    } finally {
      setGenerating(false);
    }
  };

  return (
    <DashboardShell
      role="compliance"
      userName="Morgan Lee"
      dateRange={dateRange}
      onDateRangeChange={setDateRange}
    >
      {/* Toast notifications */}
      <div className="fixed bottom-4 right-4 z-50 space-y-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`px-4 py-3 rounded-lg shadow-lg text-sm font-medium text-white transition-all ${
              t.type === "success" ? "bg-green-600" : "bg-red-600"
            }`}
          >
            {t.msg}
          </div>
        ))}
      </div>

      <div className="space-y-6">
        {/* Page header */}
        <div>
          <h2 className="text-lg font-bold text-gray-900">Compliance Command Center</h2>
          <p className="text-sm text-gray-500">
            Unified compliance health monitoring — all 8 regulatory dimensions at a glance.
          </p>
        </div>

        {/* KPI Row */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {loading ? (
            Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={i} />)
          ) : error ? (
            <div className="col-span-4 bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-xl">
              Failed to load compliance health: {error}
            </div>
          ) : health ? (
            <>
              {/* Audit Readiness Score */}
              <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
                <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                  Audit Readiness Score
                </div>
                <div className="flex items-center gap-3">
                  <div className="relative w-14 h-14">
                    <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
                      <circle cx="50" cy="50" r="40" fill="none" stroke="#e5e7eb" strokeWidth="14" />
                      <circle
                        cx="50" cy="50" r="40" fill="none"
                        stroke={ringStroke(health.overall_score)}
                        strokeWidth="14"
                        strokeDasharray={`${(health.overall_score / 100) * 251} 251`}
                        strokeLinecap="round"
                      />
                    </svg>
                    <div className="absolute inset-0 flex items-center justify-center">
                      <span className="text-xs font-bold text-gray-800">{health.overall_score.toFixed(0)}</span>
                    </div>
                  </div>
                  <div>
                    <div className={`text-xl font-bold ${scoreColor(health.overall_score) === "green" ? "text-green-700" : scoreColor(health.overall_score) === "amber" ? "text-amber-600" : "text-red-600"}`}>
                      {health.overall_score.toFixed(1)}
                    </div>
                    <div className="text-xs text-gray-500">{health.status}</div>
                  </div>
                </div>
              </div>

              {/* Active Compliance Flags */}
              <KpiCard
                label="Active Compliance Flags"
                value={String(health.failing_dimensions.length)}
                icon={health.failing_dimensions.length === 0 ? "✅" : "⚠️"}
                color={health.failing_dimensions.length === 0 ? "green" : "red"}
              />

              {/* Model Health placeholder */}
              <KpiCard
                label="Model Health"
                value="See Governance"
                icon="🏛️"
                color="amber"
              />

              {/* Fair Lending Alerts */}
              <KpiCard
                label="Fair Lending Alerts"
                value="0"
                icon="⚖️"
                color="green"
              />
            </>
          ) : null}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Dimension Score Grid */}
          <div className="lg:col-span-2 space-y-4">
            <h3 className="font-semibold text-gray-800">Dimension Scores</h3>
            {loading ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {Array.from({ length: 8 }).map((_, i) => (
                  <div key={i} className="bg-white rounded-lg border border-gray-100 p-3 animate-pulse">
                    <div className="h-3 bg-gray-200 rounded w-3/4 mb-2" />
                    <div className="h-2 bg-gray-100 rounded w-full" />
                  </div>
                ))}
              </div>
            ) : health ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {Object.entries(health.dimension_scores).map(([dim, score]) => {
                  const isFailing = health.failing_dimensions.includes(dim);
                  const barColor = score >= 80 ? "bg-green-500" : score >= 60 ? "bg-amber-400" : "bg-red-500";
                  return (
                    <div
                      key={dim}
                      className={`bg-white rounded-lg border p-3 ${isFailing ? "border-red-300" : "border-gray-100"}`}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-medium text-gray-700 capitalize">
                          {dim.replace(/_/g, " ")}
                        </span>
                        <div className="flex items-center gap-1">
                          {isFailing && (
                            <span className="text-xs bg-red-100 text-red-700 px-1.5 py-0.5 rounded font-semibold">
                              ⚠ FAILING
                            </span>
                          )}
                          <span className={`text-xs font-bold ${scoreColor(score) === "green" ? "text-green-700" : scoreColor(score) === "amber" ? "text-amber-600" : "text-red-600"}`}>
                            {score.toFixed(0)}
                          </span>
                        </div>
                      </div>
                      <div className="w-full bg-gray-100 rounded-full h-1.5">
                        <div
                          className={`h-1.5 rounded-full ${barColor}`}
                          style={{ width: `${score}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : null}
          </div>

          {/* Quick Action Sidebar */}
          <div className="space-y-4">
            <h3 className="font-semibold text-gray-800">Quick Actions</h3>
            <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 space-y-3">
              <button
                onClick={handleGeneratePackage}
                disabled={generating}
                className="w-full text-left flex items-center gap-3 text-sm font-medium text-blue-700 bg-blue-50 hover:bg-blue-100 px-4 py-3 rounded-lg transition disabled:opacity-50"
              >
                <span className="text-base">📋</span>
                <span>{generating ? "Generating…" : "Generate Audit Package"}</span>
              </button>

              <a
                href="/compliance/audit-explorer"
                className="w-full flex items-center gap-3 text-sm font-medium text-purple-700 bg-purple-50 hover:bg-purple-100 px-4 py-3 rounded-lg transition"
              >
                <span className="text-base">🔍</span>
                <span>View Decision Trace</span>
              </a>

              <a
                href="/compliance/fair-lending"
                className="w-full flex items-center gap-3 text-sm font-medium text-green-700 bg-green-50 hover:bg-green-100 px-4 py-3 rounded-lg transition"
              >
                <span className="text-base">⚖️</span>
                <span>Run Fair Lending Analysis</span>
              </a>

              <a
                href="/compliance/model-governance"
                className="w-full flex items-center gap-3 text-sm font-medium text-orange-700 bg-orange-50 hover:bg-orange-100 px-4 py-3 rounded-lg transition"
              >
                <span className="text-base">🏛️</span>
                <span>Model Governance Registry</span>
              </a>
            </div>

            {/* Failing dimensions badge list */}
            {health && health.failing_dimensions.length > 0 && (
              <div className="bg-red-50 border border-red-200 rounded-xl p-4">
                <h4 className="text-xs font-bold text-red-700 uppercase tracking-wide mb-2">
                  Failing Dimensions
                </h4>
                <div className="space-y-1">
                  {health.failing_dimensions.map((dim) => (
                    <div key={dim} className="text-xs text-red-700 flex items-center gap-1">
                      <span>⚠</span>
                      <span className="capitalize">{dim.replace(/_/g, " ")}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </DashboardShell>
  );
}
