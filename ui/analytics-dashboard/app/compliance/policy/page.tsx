"use client";

import { useState, useEffect, useCallback } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceLine,
  Cell,
} from "recharts";
import {
  fetchPolicyAdherence,
  fetchPendingWaivers,
  approveWaiver,
  denyWaiver,
  fetchFairLendingReport,
  triggerExamPacket,
  fetchExamPackets,
  type PolicyAdherenceReport,
  type PolicyRuleStats,
  type Waiver,
  type FairLendingReport,
} from "@/lib/api";

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

function fmtPct(n: number) {
  return `${(n * 100).toFixed(1)}%`;
}

const STATUS_STYLES: Record<string, string> = {
  Healthy: "bg-emerald-900 text-emerald-300 border-emerald-700",
  Watch: "bg-amber-900 text-amber-300 border-amber-700",
  Breach: "bg-red-900 text-red-300 border-red-700",
};

const GAUGE_COLOR: Record<string, string> = {
  Healthy: "#10b981",
  Watch: "#f59e0b",
  Breach: "#ef4444",
};

function overallStatusClass(rate: number): string {
  if (rate >= 0.95) return GAUGE_COLOR.Healthy;
  if (rate >= 0.85) return GAUGE_COLOR.Watch;
  return GAUGE_COLOR.Breach;
}

// ─────────────────────────────────────────────────────────────────────────────
// Compliance Score Gauge
// ─────────────────────────────────────────────────────────────────────────────

function ComplianceGauge({ rate, total }: { rate: number; total: number }) {
  const color = overallStatusClass(rate);
  const pct = Math.round(rate * 100);
  const dasharray = 251; // circumference of r=40 circle
  const dashoffset = dasharray * (1 - rate);

  return (
    <div className="flex flex-col items-center">
      <svg width={110} height={110} aria-label={`Compliance score gauge: ${pct}%`}>
        <circle cx={55} cy={55} r={40} fill="none" stroke="#334155" strokeWidth={10} />
        <circle
          cx={55}
          cy={55}
          r={40}
          fill="none"
          stroke={color}
          strokeWidth={10}
          strokeDasharray={dasharray}
          strokeDashoffset={dashoffset}
          strokeLinecap="round"
          transform="rotate(-90 55 55)"
        />
        <text x={55} y={52} textAnchor="middle" fill="white" fontSize={20} fontWeight="bold">
          {pct}%
        </text>
        <text x={55} y={68} textAnchor="middle" fill="#94a3b8" fontSize={10}>
          Compliance
        </text>
      </svg>
      <p className="text-slate-400 text-xs mt-1">{total.toLocaleString()} decisions evaluated</p>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Policy Rules Table
// ─────────────────────────────────────────────────────────────────────────────

function PolicyRulesTable({ rules }: { rules: PolicyRuleStats[] }) {
  const sorted = [...rules].sort((a, b) => {
    const order = { Breach: 0, Watch: 1, Healthy: 2 };
    if (order[a.status] !== order[b.status]) return order[a.status] - order[b.status];
    return a.compliance_rate - b.compliance_rate;
  });

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" aria-label="Policy rules compliance table">
        <caption className="sr-only">Policy rules sorted by status (Breach first)</caption>
        <thead className="text-slate-400 text-xs uppercase border-b border-slate-700">
          <tr>
            <th className="py-2 px-3 text-left">Rule</th>
            <th className="py-2 px-3 text-right">Evaluated</th>
            <th className="py-2 px-3 text-right">Compliance %</th>
            <th className="py-2 px-3 text-right">Exceptions</th>
            <th className="py-2 px-3 text-right">Waivers</th>
            <th className="py-2 px-3 text-center">Status</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr key={r.rule_id} className="border-b border-slate-800 hover:bg-slate-700/30">
              <td className="py-2 px-3">
                <p className="text-slate-200 font-medium">{r.rule_id}</p>
                <p className="text-slate-400 text-xs">{r.rule_description}</p>
              </td>
              <td className="py-2 px-3 text-right text-slate-300">{r.decisions_evaluated}</td>
              <td className="py-2 px-3 text-right">
                <span className={r.compliance_rate >= 0.95 ? "text-emerald-400" : r.compliance_rate >= 0.85 ? "text-amber-400" : "text-red-400"}>
                  {fmtPct(r.compliance_rate)}
                </span>
                <span className={`ml-1 text-xs ${r.trend_30d < 0 ? "text-red-400" : "text-emerald-400"}`}>
                  {r.trend_30d >= 0 ? "▲" : "▼"} {fmtPct(Math.abs(r.trend_30d))}
                </span>
              </td>
              <td className="py-2 px-3 text-right text-red-400">{r.exception_count}</td>
              <td className="py-2 px-3 text-right text-blue-400">{r.waiver_count}</td>
              <td className="py-2 px-3 text-center">
                <span className={`px-2 py-0.5 text-xs font-medium rounded border ${STATUS_STYLES[r.status]}`}>
                  {r.status}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Waiver Card
// ─────────────────────────────────────────────────────────────────────────────

function WaiverCard({
  waiver,
  onRefresh,
}: {
  waiver: Waiver;
  onRefresh: () => void;
}) {
  const [confirming, setConfirming] = useState<"approve" | "deny" | null>(null);
  const [denyReason, setDenyReason] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const age = Math.round(
    (Date.now() - new Date(waiver.requested_at).getTime()) / (1000 * 60 * 60)
  );

  const handleApprove = async () => {
    setLoading(true);
    setError(null);
    try {
      await approveWaiver(waiver.waiver_id, "current_user");
      setConfirming(null);
      onRefresh();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to approve");
    } finally {
      setLoading(false);
    }
  };

  const handleDeny = async () => {
    if (!denyReason) return;
    setLoading(true);
    setError(null);
    try {
      await denyWaiver(waiver.waiver_id, "current_user", denyReason);
      setConfirming(null);
      onRefresh();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to deny");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="rounded-lg bg-slate-700/50 border border-slate-600 p-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-sm font-medium text-white">{waiver.policy_rule_id}</p>
          <p className="text-xs text-slate-400 mt-0.5">App: {waiver.application_id}</p>
          <p className="text-xs text-slate-400">By: {waiver.requested_by} · {age}h ago</p>
          <p className="text-xs text-slate-300 mt-1 italic">{waiver.waiver_reason}</p>
        </div>
        {confirming === null && (
          <div className="flex gap-1 shrink-0">
            <button
              onClick={() => setConfirming("approve")}
              className="px-2 py-1 bg-emerald-700 hover:bg-emerald-600 rounded text-xs font-medium"
              aria-label={`Approve waiver ${waiver.waiver_id}`}
            >
              Approve
            </button>
            <button
              onClick={() => setConfirming("deny")}
              className="px-2 py-1 bg-red-800 hover:bg-red-700 rounded text-xs font-medium"
              aria-label={`Deny waiver ${waiver.waiver_id}`}
            >
              Deny
            </button>
          </div>
        )}
      </div>

      {confirming === "approve" && (
        <div className="mt-2 space-y-2">
          <p className="text-xs text-amber-300">Confirm approval? (You cannot approve your own requests)</p>
          <div className="flex gap-2">
            <button
              onClick={handleApprove}
              disabled={loading}
              className="px-3 py-1 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 rounded text-xs"
            >
              {loading ? "…" : "Yes, Approve"}
            </button>
            <button onClick={() => setConfirming(null)} className="px-3 py-1 bg-slate-600 rounded text-xs">Cancel</button>
          </div>
        </div>
      )}

      {confirming === "deny" && (
        <div className="mt-2 space-y-2">
          <input
            type="text"
            placeholder="Denial reason (required)"
            value={denyReason}
            onChange={(e) => setDenyReason(e.target.value)}
            className="w-full bg-slate-700 text-white text-xs rounded px-2 py-1 border border-slate-600"
          />
          <div className="flex gap-2">
            <button
              onClick={handleDeny}
              disabled={loading || !denyReason}
              className="px-3 py-1 bg-red-700 hover:bg-red-600 disabled:opacity-50 rounded text-xs"
            >
              {loading ? "…" : "Deny"}
            </button>
            <button onClick={() => setConfirming(null)} className="px-3 py-1 bg-slate-600 rounded text-xs">Cancel</button>
          </div>
        </div>
      )}

      {error && <p className="text-xs text-red-400 mt-1">{error}</p>}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Fair Lending AIR Panel
// ─────────────────────────────────────────────────────────────────────────────

function FairLendingPanel({ report }: { report: FairLendingReport | null }) {
  if (!report) return <p className="text-slate-400 text-xs">Loading fair lending data…</p>;

  const airData = Object.entries(report.air_by_class ?? {}).map(([cls, air]) => ({
    name: cls.replace(/_/g, " "),
    air: typeof air === "number" ? parseFloat(air.toFixed(4)) : 0,
  }));

  if (!airData.length) return <p className="text-slate-400 text-xs">No AIR data available.</p>;

  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart data={airData} layout="vertical" aria-label="Fair lending AIR by protected class">
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
        <XAxis type="number" domain={[0, 1.2]} tick={{ fill: "#94a3b8", fontSize: 10 }} />
        <YAxis type="category" dataKey="name" tick={{ fill: "#94a3b8", fontSize: 10 }} width={80} />
        <Tooltip contentStyle={{ background: "#1e293b", border: "none" }} />
        <ReferenceLine x={0.8} stroke="#ef4444" strokeDasharray="4 4" label={{ value: "4/5ths", fill: "#ef4444", fontSize: 10 }} />
        <Bar dataKey="air" name="AIR">
          {airData.map((entry) => (
            <Cell key={entry.name} fill={entry.air >= 0.8 ? "#10b981" : "#ef4444"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────────────

const PERIODS = ["30d", "90d", "ytd"] as const;
type Period = (typeof PERIODS)[number];

export default function CompliancePolicyPage() {
  const [period, setPeriod] = useState<Period>("30d");
  const [adherence, setAdherence] = useState<PolicyAdherenceReport | null>(null);
  const [waivers, setWaivers] = useState<Waiver[]>([]);
  const [fairLending, setFairLending] = useState<FairLendingReport | null>(null);
  const [packetStatus, setPacketStatus] = useState<"idle" | "generating" | "ready" | "error">("idle");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadAdherence = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [adh, flr] = await Promise.allSettled([
        fetchPolicyAdherence(period),
        fetchFairLendingReport(),
      ]);
      if (adh.status === "fulfilled") setAdherence(adh.value);
      else if (adh.reason?.message === "FORBIDDEN") setError("Insufficient permissions to view policy adherence.");
      if (flr.status === "fulfilled") setFairLending(flr.value);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load compliance data");
    } finally {
      setLoading(false);
    }
  }, [period]);

  const loadWaivers = useCallback(async () => {
    try {
      const ws = await fetchPendingWaivers();
      setWaivers(ws);
    } catch {
      setWaivers([]);
    }
  }, []);

  useEffect(() => {
    loadAdherence();
    loadWaivers();
  }, [loadAdherence, loadWaivers]);

  const handleGeneratePacket = async () => {
    setPacketStatus("generating");
    try {
      await triggerExamPacket();
      // Poll for ready
      const poll = setInterval(async () => {
        try {
          const packets = await fetchExamPackets();
          const latest = packets[0];
          if (latest?.status === "ready") {
            setPacketStatus("ready");
            clearInterval(poll);
          }
        } catch {
          // keep polling
        }
      }, 3000);
      setTimeout(() => {
        clearInterval(poll);
        if (packetStatus === "generating") setPacketStatus("ready");
      }, 30000);
    } catch {
      setPacketStatus("error");
    }
  };

  return (
    <div className="min-h-screen bg-slate-900 text-white p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Compliance &amp; Waiver Dashboard</h1>
          <p className="text-slate-400 text-sm mt-1">Policy adherence, fair lending, and waiver management</p>
        </div>

        {/* Period selector */}
        <div className="flex gap-2" role="tablist" aria-label="Reporting period">
          {PERIODS.map((p) => (
            <button
              key={p}
              role="tab"
              aria-selected={period === p}
              onClick={() => setPeriod(p)}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition ${
                period === p ? "bg-indigo-600 text-white" : "bg-slate-800 text-slate-300 hover:bg-slate-700"
              }`}
            >
              {p === "ytd" ? "YTD" : p}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-lg bg-red-900/40 border border-red-700 p-3 text-red-300 text-sm">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Left 2/3 */}
        <div className="xl:col-span-2 space-y-6">
          {/* Compliance Score KPI */}
          {loading && !adherence ? (
            <div className="h-40 rounded-xl bg-slate-800 animate-pulse" />
          ) : adherence ? (
            <div className="rounded-xl bg-slate-800 border border-slate-700 p-6 flex items-center gap-8">
              <ComplianceGauge
                rate={adherence.overall_compliance_rate}
                total={adherence.total_decisions}
              />
              <div>
                <p className="text-sm text-slate-400 mb-2">{adherence.summary}</p>
                <p className="text-xs text-slate-500">Period: {adherence.period} · Generated: {new Date(adherence.generated_at).toLocaleString()}</p>
              </div>
            </div>
          ) : null}

          {/* Policy Rules Table */}
          <div className="rounded-xl bg-slate-800 border border-slate-700 overflow-hidden">
            <div className="p-4 border-b border-slate-700">
              <h2 className="text-sm font-semibold text-slate-300">Policy Rules</h2>
            </div>
            {adherence ? (
              <PolicyRulesTable rules={adherence.rules} />
            ) : (
              <div className="p-6 space-y-2">
                {Array.from({ length: 5 }).map((_, i) => (
                  <div key={i} className="h-10 rounded bg-slate-700 animate-pulse" />
                ))}
              </div>
            )}
          </div>

          {/* Fair Lending AIR */}
          <div className="rounded-xl bg-slate-800 border border-slate-700 p-4">
            <h2 className="text-sm font-semibold text-slate-300 mb-3">
              Fair Lending — Adverse Impact Ratio by Protected Class
            </h2>
            <p className="text-xs text-slate-400 mb-3">
              Red dashed line at 0.80 (4/5ths rule). Bars below = potential disparate impact.
            </p>
            <FairLendingPanel report={fairLending} />
          </div>
        </div>

        {/* Right 1/3 */}
        <div className="space-y-6">
          {/* Pending Waivers */}
          <div className="rounded-xl bg-slate-800 border border-slate-700 p-4">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-slate-300">
                Pending Waivers
                {waivers.length > 0 && (
                  <span className="ml-2 px-1.5 py-0.5 bg-amber-700 text-amber-200 text-xs rounded">
                    {waivers.length}
                  </span>
                )}
              </h2>
              <button
                onClick={loadWaivers}
                className="text-xs text-slate-400 hover:text-white"
                aria-label="Refresh waivers"
              >
                ↻
              </button>
            </div>
            {waivers.length === 0 ? (
              <p className="text-slate-400 text-sm">No pending waivers.</p>
            ) : (
              <div className="space-y-3">
                {waivers.map((w) => (
                  <WaiverCard key={w.waiver_id} waiver={w} onRefresh={loadWaivers} />
                ))}
              </div>
            )}
          </div>

          {/* Exam Packet Generator */}
          <div className="rounded-xl bg-slate-800 border border-slate-700 p-4">
            <h2 className="text-sm font-semibold text-slate-300 mb-3">Exam Packet</h2>
            <p className="text-xs text-slate-400 mb-4">
              Generate a regulatory exam packet with adverse actions, fair lending, and policy snapshots.
            </p>
            <button
              onClick={handleGeneratePacket}
              disabled={packetStatus === "generating"}
              className="w-full py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-sm font-medium transition"
              aria-label="Generate exam packet"
            >
              {packetStatus === "generating" ? "Generating…" : "Generate Exam Packet"}
            </button>
            {packetStatus === "generating" && (
              <div className="mt-2 h-1.5 bg-slate-700 rounded overflow-hidden">
                <div className="h-full bg-indigo-500 animate-pulse w-3/4" />
              </div>
            )}
            {packetStatus === "ready" && (
              <p className="mt-2 text-xs text-emerald-400">
                ✓ Exam packet ready. Download from the reports section.
              </p>
            )}
            {packetStatus === "error" && (
              <p className="mt-2 text-xs text-red-400">Generation failed. Try again.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
