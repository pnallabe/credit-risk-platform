"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ComplianceHealth {
  overall_score: number;
  dimension_scores: Record<string, number>;
  failing_dimensions: string[];
  computed_at: string;
}

interface ExamPacket {
  packet_id: string;
  tenant_id: string;
  template: string;
  from_date: string;
  to_date: string;
  generated_at: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const API_URL = process.env.NEXT_PUBLIC_DECISION_API_URL ?? "http://localhost:8000";

function getToken() {
  return typeof window !== "undefined" ? (localStorage.getItem("decision_api_token") ?? "") : "";
}

async function apiFetch<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function scoreColor(score: number) {
  if (score >= 80) return "text-green-700 bg-green-50 border-green-200";
  if (score >= 60) return "text-amber-700 bg-amber-50 border-amber-200";
  return "text-red-700 bg-red-50 border-red-200";
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function RegulatorOverviewPage() {
  const [health, setHealth] = useState<ComplianceHealth | null>(null);
  const [packets, setPackets] = useState<ExamPacket[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      apiFetch<ComplianceHealth>("/v1/compliance/health"),
      apiFetch<{ packets: ExamPacket[] }>("/v1/audit/packets"),
    ])
      .then(([healthData, packetData]) => {
        setHealth(healthData);
        setPackets((packetData.packets ?? []).slice(0, 2));
      })
      .catch((err) => setError(String(err)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48 text-gray-400 text-sm animate-pulse">
        Loading regulator overview…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load data: {error}
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-4xl">
      <div>
        <h1 className="text-xl font-bold text-gray-900">Regulator Overview</h1>
        <p className="text-sm text-gray-500 mt-1">
          Read-only view of platform compliance health and exam packages.
        </p>
      </div>

      {/* Compliance health score */}
      {health && (
        <div className={`rounded-xl border p-6 ${scoreColor(health.overall_score)}`}>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider opacity-70">
                Audit Readiness Score
              </p>
              <p className="text-4xl font-black mt-1">{health.overall_score}</p>
              <p className="text-xs mt-1 opacity-70">
                Computed: {new Date(health.computed_at).toLocaleString()}
              </p>
            </div>
            <svg viewBox="0 0 100 100" className="w-20 h-20 -rotate-90">
              <circle cx="50" cy="50" r="40" fill="none" stroke="currentColor" strokeWidth="12" opacity={0.2} />
              <circle
                cx="50"
                cy="50"
                r="40"
                fill="none"
                stroke="currentColor"
                strokeWidth="12"
                strokeDasharray={`${(health.overall_score / 100) * 251} 251`}
                strokeLinecap="round"
              />
            </svg>
          </div>
          {health.failing_dimensions.length > 0 && (
            <div className="mt-4">
              <p className="text-xs font-semibold mb-1">Failing Dimensions:</p>
              <div className="flex flex-wrap gap-1.5">
                {health.failing_dimensions.map((d) => (
                  <span key={d} className="text-xs font-medium px-2 py-0.5 rounded-full bg-white/60 border border-current">
                    {d}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Dimension score grid */}
      {health && Object.keys(health.dimension_scores).length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-gray-700 mb-3">Dimension Scores</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {Object.entries(health.dimension_scores).map(([dim, score]) => {
              const failing = health.failing_dimensions.includes(dim);
              return (
                <div key={dim} className="bg-white rounded-lg border border-gray-100 p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-medium text-gray-600 capitalize">{dim.replace(/_/g, " ")}</span>
                    {failing && (
                      <span className="text-xs font-semibold text-red-600 bg-red-50 border border-red-200 rounded-full px-2 py-0.5">
                        Failing
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full ${score >= 80 ? "bg-green-500" : score >= 60 ? "bg-amber-400" : "bg-red-500"}`}
                        style={{ width: `${score}%` }}
                      />
                    </div>
                    <span className="text-xs font-bold text-gray-800 w-8 text-right">{score}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Recent exam packets */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-gray-700">Recent Exam Packets</h2>
          <Link href="/regulator/exam-packets" className="text-xs text-blue-600 hover:underline">
            View all →
          </Link>
        </div>
        {packets.length === 0 ? (
          <p className="text-sm text-gray-400">No exam packets generated yet.</p>
        ) : (
          <div className="space-y-2">
            {packets.map((p) => (
              <div key={p.packet_id} className="bg-white rounded-lg border border-gray-100 p-4 flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-900">{p.template} — {p.from_date} to {p.to_date}</p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Generated: {new Date(p.generated_at).toLocaleDateString()} · ID: {p.packet_id.slice(0, 8)}…
                  </p>
                </div>
                <Link
                  href="/regulator/exam-packets"
                  className="text-xs text-blue-600 hover:underline"
                >
                  Download →
                </Link>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Quick navigation */}
      <div className="flex gap-3">
        <Link
          href="/regulator/audit-records"
          className="flex-1 rounded-lg border border-gray-200 bg-white p-4 text-center text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
        >
          🔍 Search Audit Records
        </Link>
        <Link
          href="/regulator/exam-packets"
          className="flex-1 rounded-lg border border-gray-200 bg-white p-4 text-center text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
        >
          📦 Exam Packets
        </Link>
      </div>
    </div>
  );
}
